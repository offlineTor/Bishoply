import copy
import os
import struct
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import chess
import chess.engine
import chess.polyglot
from backend.analysis import config as C
from backend.analysis.accuracy import measure
from backend.analysis.book import lookup
from backend.analysis.engine import Engine, outcome
from backend.analysis.model import normal_quality, classify_move
from backend.analysis.worker import analyze_move, verification_reasons


def candidate(uci, units=1000, mate=None, pv=None, gain=0):
    return {'move':uci, 'outcome_units':units, 'outcome':units/2000, 'mate':mate, 'cp':0 if mate is None else None,
            'pv_uci':pv or [uci], 'pv':pv or [uci], 'material_gain':gain, 'depth':22}


class SharedModelTests(unittest.TestCase):
    def test_exact_boundaries(self):
        for upper,label in C.THRESHOLDS:
            self.assertEqual(normal_quality(upper), label)
            self.assertNotEqual(normal_quality(upper+1), label)
        # .800 - .795 is exactly 10 E2000 units, no floating-point subtraction.
        self.assertEqual(normal_quality(1600-1590), 'Best')

    def test_white_black_wdl_and_mate(self):
        info={'score':chess.engine.PovScore(chess.engine.Cp(50),chess.WHITE), 'wdl':chess.engine.PovWdl(chess.engine.Wdl(700,200,100),chess.WHITE)}
        self.assertEqual(outcome(info,chess.WHITE)['outcome_units'],1600)
        self.assertEqual(outcome(info,chess.BLACK)['outcome_units'],400)
        self.assertEqual(outcome({'score':chess.engine.PovScore(chess.engine.Mate(3),chess.BLACK)},chess.BLACK)['outcome_units'],2000)

    def test_forced_move_and_accuracy_exclusions(self):
        board=chess.Board('7k/8/5K2/8/8/8/8/1Q6 b - - 0 1')
        self.assertEqual(board.legal_moves.count(),1)
        move=next(iter(board.legal_moves))
        result=classify_move(board,move,[candidate(move.uci(),0)])
        self.assertEqual((result['classification'],result['loss_units']),('Forced',0))
        row={**result,'evaluation_before':{'outcome_units':0},'evaluation_after':{'outcome_units':0}}
        self.assertIsNone(measure([row])['value'])
        for field in ('book','assisted'):
            self.assertIsNone(measure([{**row,'forced_move':False,field:True}])['value'])

    def test_special_awards_stay_disabled(self):
        for practice in (False, True):
            result=classify_move(chess.Board(),chess.Move.from_uci('e2e4'),
                [candidate('e2e4',1800),candidate('d2d4',500)],practice=practice,verified=True,stable=True)
            self.assertNotIn(result['classification'], ('Great','Brilliant'))

    def test_mate_preserved_lost_and_miss(self):
        board=chess.Board()
        best=candidate('e2e4',2000,3)
        played=candidate('d2d4',1998)
        result=classify_move(board,chess.Move.from_uci('d2d4'),[best,played],verified=True,stable=True)
        self.assertEqual(result['classification'],'Miss')
        self.assertEqual(result['mate_policy']['transition'],'lost')
        preserved=classify_move(board,chess.Move.from_uci('e2e4'),[best,played],verified=True,stable=True)
        self.assertEqual(preserved['mate_policy']['transition'],'preserved')
        gain=classify_move(board,chess.Move.from_uci('d2d4'),[candidate('e2e4',1800,gain=500),candidate('d2d4',1000)],verified=True,stable=True)
        self.assertEqual(gain['evidence']['missed_opportunity']['type'],'major_material_win')

    def test_genuine_polyglot_membership(self):
        board=chess.Board(); move=chess.Move.from_uci('e2e4')
        with tempfile.TemporaryDirectory() as directory:
            path=directory+'/test.bin'
            raw=move.to_square | (move.from_square << 6)
            with open(path,'wb') as out:
                out.write(struct.pack('>QHHI',chess.polyglot.zobrist_hash(board),raw,1,0))
            with patch.dict(os.environ,{'BISHOPLY_POLYGLOT_BOOK':path}):
                self.assertEqual(lookup(board,move)['book_move'],'e2e4')
                self.assertIsNone(lookup(board,chess.Move.from_uci('d2d4')))

    def test_book_label_requires_practice_and_actual_membership(self):
        board=chess.Board(); move=chess.Move.from_uci('e2e4')
        cs=[candidate('e2e4'),candidate('d2d4',900)]
        self.assertEqual(classify_move(board,move,cs,practice=True,book={'book_source':'fixture'})['classification'],'Book')
        self.assertNotEqual(classify_move(board,move,cs,practice=False,book={'book_source':'fixture'})['classification'],'Book')
        self.assertNotEqual(classify_move(board,move,cs,practice=True)['classification'],'Book')

    def test_insufficient_depth_and_bound_scores_fail_closed(self):
        engine=Engine(); engine.engine=MagicMock(); engine.raw_search=MagicMock()
        board=chess.Board()
        engine.raw_search.return_value=[{'depth':C.NORMAL_DEPTH-1,'pv':[chess.Move.from_uci('e2e4')]}]
        with self.assertRaisesRegex(RuntimeError,'depth'):
            engine.search(board,C.NORMAL_DEPTH)
        engine.raw_search.return_value=[{'depth':C.NORMAL_DEPTH,'pv':[chess.Move.from_uci('e2e4')],'lowerbound':True}]
        with self.assertRaisesRegex(RuntimeError,'Bound-only'):
            engine.search(board,C.NORMAL_DEPTH)

    def test_miss_requires_deeper_stable_evidence(self):
        board=chess.Board(); move=chess.Move.from_uci('d2d4')
        cs=[candidate('e2e4',2000,3),candidate('d2d4',1700)]
        for verified,stable in ((False,True),(True,False)):
            self.assertNotEqual(classify_move(board,move,cs,verified=verified,stable=stable)['classification'],'Miss')

    def test_decided_moves_do_not_dilute_accuracy(self):
        row={'loss_units':400,'evaluation_before':{'outcome_units':1000},'evaluation_after':{'outcome_units':600}}
        dead={'loss_units':0,'evaluation_before':{'outcome_units':0},'evaluation_after':{'outcome_units':0}}
        self.assertEqual(measure([row])['value'],measure([row]+[dead]*100)['value'])

    def test_two_stage_common_root_contract(self):
        class Fake:
            provenance={'engine':{'name':'Stockfish 19'}}
            calls=[]
            def candidates(self,board,played,depth,count,retain=()):
                self.calls.append((board.fen(),played.uci(),depth))
                cs=[candidate('e2e4',1000),candidate('d2d4',990)]
                return {'candidates':copy.deepcopy(cs),'discovery':copy.deepcopy(cs),'depth':depth}
        engine=Fake(); board=chess.Board()
        result=analyze_move(engine,board,chess.Move.from_uci('d2d4'))
        self.assertTrue(result['verification_occurred'])
        self.assertEqual([c[2] for c in engine.calls],[C.NORMAL_DEPTH,C.VERIFY_DEPTH])
        self.assertTrue(all(c[0]==board.fen() for c in engine.calls))
        self.assertEqual(result['classification'],'Best')


class RealEngineTests(unittest.TestCase):
    def test_real_black_and_repeatable_candidate_scores(self):
        board=chess.Board('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1').mirror()
        move=chess.Move.from_uci('f2g2')
        with Engine() as engine:
            first=analyze_move(engine,board,move)
            second=analyze_move(engine,board,move)
        self.assertEqual(first['color'],'black')
        self.assertEqual(first['loss_units'],0)
        self.assertEqual(first['white_outcome'],0)
        for key in ('classification','loss_units','best_move'):
            self.assertEqual(first[key],second[key])

    def test_real_common_root_provenance_and_depth(self):
        board=chess.Board('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1')
        with Engine() as engine:
            result=analyze_move(engine,board,chess.Move.from_uci('f7g7'))
            self.assertEqual(len(engine.provenance['binary_sha256']),64)
        self.assertTrue(result['verification_occurred'])
        self.assertEqual(result['mate_policy']['transition'],'terminal_checkmate')
        for row in result['verification']['authoritative_pass']['candidates']:
            self.assertEqual(row['root_fen'],board.fen())
            self.assertGreaterEqual(row['depth'],C.VERIFY_DEPTH)
            self.assertEqual(row['multipv'],1)
        self.assertEqual(result['loss_units'],0)
