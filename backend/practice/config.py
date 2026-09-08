"""Central, experimental Bishoply bot calibration. Strength is NOT verified Elo.
UCI_Elo is an engine control, not a conversion to Estimated Bot Strength.
All style/weakening choices are constrained to scored legal candidates.
"""
from dataclasses import asdict, dataclass

VERSION = 'bishoply-bots-v1-experimental'
LABEL = 'Estimated Bot Strength'
JOB_TIMEOUT = 8.0
MAX_ENGINE_JOBS = 2
ASSESS_DEPTH = 10
ASSESS_SECONDS = .35
BASE_SECONDS = .20
CROWN_DEPTH = 18
CROWN_SECONDS = .8
HINT_DEPTH = 14
HINT_SECONDS = .5
MAX_HISTORY_PLIES = 1000


@dataclass(frozen=True)
class Bot:
    bot_id: str
    display_name: str
    estimated_strength: int
    community_level: str
    personality: str
    candidates: int
    max_cp_loss: int
    max_outcome_loss: int
    variety_probability: float
    style: str
    search_seconds: float = .2
    search_depth: int | None = None
    tactical_awareness: float = .5

    def public(self):
        # This is a public roster contract. Engine tuning, weakening
        # thresholds, and timing controls remain server-side.
        return {'bot_id': self.bot_id, 'display_name': self.display_name,
                'estimated_strength': self.estimated_strength,
                'community_level': self.community_level, 'personality': self.personality,
                'strength_label': LABEL, 'calibration_version': VERSION,
                'icon_path': f'/assets/bots/{self.bot_id}.png'}


ROSTER = (
    Bot('scout','Scout',600,'Beginner','Forgiving; reasonable lower-ranked moves',8,220,300,.80,'forgiving',.12,8,.25),
    Bot('tempo','Tempo',800,'Casual','Natural development; occasional tactical misses',7,180,260,.65,'development',.16,9,.35),
    Bot('fork','Fork',1000,'Developing','Knight tactics, with bounded inconsistency',6,150,220,.55,'knight',.19,10,.45),
    Bot('gambit','Gambit',1200,'Club Player','Active play and attacking chances',6,120,180,.50,'attack',.23,11,.55),
    Bot('castle','Castle',1400,'Strong Club','King safety and positional restraint',5,90,140,.40,'safety',.28,12,.62),
    Bot('tactician','Tactician',1600,'Tournament Player','Checks, captures and tactical lines',5,70,100,.35,'tactical',.34,13,.75),
    Bot('endgame','Endgame',1800,'Expert','Increasing precision as material decreases',4,60,80,.30,'technical',.40,14,.82),
    Bot('vanguard','Vanguard',2000,'Advanced / Master Strength','Balanced strong play',4,40,60,.20,'balanced',.48,15,.88),
    Bot('maestro','Maestro',2200,'Elite','Strong play with restrained stylistic variety',3,25,40,.15,'positional',.60,16,.93),
    Bot('crown','Crown',2400,'Grandmaster Strength','Strongest normal Bishoply engine behavior',1,0,0,0,'strongest',.90,18,1.0),
)
BOTS = {bot.bot_id: bot for bot in ROSTER}
