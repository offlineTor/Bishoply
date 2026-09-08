"""Central, experimental Bishoply bot calibration. Strength is NOT verified Elo.
UCI_Elo is an engine control, not a conversion to Estimated Bot Strength.
All style/weakening choices are constrained to scored legal candidates.
"""
from dataclasses import asdict, dataclass

VERSION = 'bishoply-bots-v2-calibrated'
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
    selection_temperature: float = 1.0
    mistake_frequency: float = 0.0

    def public(self):
        # This is a public roster contract. Engine tuning, weakening
        # thresholds, and timing controls remain server-side.
        return {'bot_id': self.bot_id, 'display_name': self.display_name,
                'estimated_strength': self.estimated_strength,
                'community_level': self.community_level, 'personality': self.personality,
                'strength_label': LABEL, 'calibration_version': VERSION,
                'icon_path': f'/assets/bots/{self.bot_id}.png'}


ROSTER = (
    # Variety and loss bands are deliberately graduated.  These are practical
    # Bishoply estimates, not claims of certified Elo.
    Bot('scout','Scout',600,'Beginner','Forgiving; reasonable lower-ranked moves',8,420,520,.98,'forgiving',.10,7,.20,7.0,.42),
    Bot('tempo','Tempo',800,'Casual','Natural development; occasional tactical misses',7,250,330,.82,'development',.14,8,.32,4.1,.27),
    Bot('fork','Fork',1000,'Developing','Knight tactics, with bounded inconsistency',6,195,270,.70,'knight',.18,9,.55,3.2,.21),
    Bot('gambit','Gambit',1200,'Club Player','Active play and attacking chances',6,155,215,.62,'attack',.22,10,.60,2.6,.17),
    Bot('castle','Castle',1400,'Strong Club','King safety and positional restraint',5,125,170,.52,'safety',.27,11,.66,2.05,.13),
    Bot('tactician','Tactician',1600,'Tournament Player','Checks, captures and tactical lines',5,95,130,.43,'tactical',.33,12,.80,1.55,.09),
    Bot('endgame','Endgame',1800,'Expert','Increasing precision as material decreases',5,180,130,.62,'technical',.40,13,.86,1.8,.12),
    Bot('vanguard','Vanguard',2000,'Advanced / Master Strength','Balanced strong play',4,100,110,.48,'balanced',.48,14,.90,1.4,.075),
    Bot('maestro','Maestro',2200,'Elite','Strong play with restrained stylistic variety',3,42,55,.24,'positional',.60,15,.95,.82,.03),
    Bot('crown','Crown',2400,'Grandmaster Strength','Strongest normal Bishoply engine behavior',2,22,30,.12,'strongest',.90,17,1.0,.35,0),
)
BOTS = {bot.bot_id: bot for bot in ROSTER}
