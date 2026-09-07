"""All public model decisions live here. Units: E2000 = 2*wins + draws.
WDL is validated as integers summing to 1000; comparisons NEVER use floats.
Thresholds are inclusive. Calibration, especially special labels, is experimental.
"""
MODEL_VERSION = "bishoply-common-root-v2"
CLASSIFIER_VERSION = "bishoply-classifier-v2"
ACCURACY_VERSION = "bishoply-accuracy-v2-experimental"
EXPECTED_ENGINE = "Stockfish 19"
NORMAL_DEPTH = 20
VERIFY_DEPTH = 24
DISCOVERY_PVS = 4
VERIFY_PVS = 6
THREADS = 1
HASH_MB = 64
SEARCH_SECONDS = 45
THRESHOLDS = ((10, "Best"), (30, "Excellent"), (80, "Good"),
              (160, "Inaccuracy"), (360, "Mistake"))
BOUNDARY_MARGIN = 4
DISAGREEMENT = 100
ORDER_MARGIN = 10
NONWINNING_CEILING = 1300
DECIDED_LOW = 40
DECIDED_HIGH = 1960
MATE_LOSS_FLOOR = 360
MISS_GAP = 160
MATERIAL_GAIN = 300
CATEGORIES = ("Brilliant", "Great", "Best", "Excellent", "Good", "Book",
              "Inaccuracy", "Mistake", "Miss", "Blunder", "Forced")
PIECE_VALUES = {1: 100, 2: 320, 3: 330, 4: 500, 5: 900, 6: 0}

# Preliminary review only; never an authoritative public classification.
FAST_DEPTH = 12

# Intelligence V1 is additive. Set BISHOPLY_INTELLIGENCE_V2=1 for consumers
# opting into canonical WDL-derived move/game accuracy fields; legacy review
# fields remain available during migration.
INTELLIGENCE_FEATURE_FLAG = "BISHOPLY_INTELLIGENCE_V2"
