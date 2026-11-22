"""Game-wide constants. Pure Python, no engine imports."""
from .device import IS_ANDROID

# --- The highway -----------------------------------------------------------
EARTH_LOOP_M = 40_075_000.0      # one lap around the Earth (metres)
LANES = 1_000_000                # total lanes
LANE_W = 4.0                     # lane width (metres)
BAND_LANES = 48                  # lanes per deck band
GAP_W = 24.0                     # glass median between bands (metres)
BAND_W = BAND_LANES * LANE_W     # 192 m of asphalt per band
BAND_PERIOD = BAND_W + GAP_W     # 216 m from band start to next band start
NUM_BANDS = (LANES + BAND_LANES - 1) // BAND_LANES

DECK_Y = 0.0                     # highway deck height (world units)
DECK_THICK = 2.0
CITY_Y = -60.0                   # city ground level, under the highway
MAX_ALT = 600.0                  # flying ceiling

# --- The map ---------------------------------------------------------------
EARTH_R = 6_371_000.0            # map radius of the highway ring's inner edge
MAP_SIZE_M = 1e12                # map is 1,000,000,000 km wide

# --- World streaming -------------------------------------------------------
DECK_BEHIND = 600.0              # metres of deck drawn behind the player
DECK_AHEAD = 1800.0              # metres of deck drawn ahead
BANDS_EACH_SIDE = 3              # bands drawn left/right of the player
CITY_CHUNK = 200.0               # city chunk size (metres)
CITY_RADIUS_X = 3                # chunks each side laterally
CITY_BEHIND = 2                  # chunks behind
CITY_AHEAD = 5                   # chunks ahead
CITY_BUILDS_PER_FRAME = 2
CITY_CACHE = 320
FOG_START = 120.0
FOG_END = 1150.0

# --- Traffic ---------------------------------------------------------------
MAX_TRAFFIC = 140
TRAFFIC_LANES_EACH_SIDE = 18
TRAFFIC_BEHIND = 380.0
TRAFFIC_AHEAD = 950.0

# --- Time ------------------------------------------------------------------
DAY_LENGTH_S = 24 * 60.0         # one in-game day = 24 real minutes
START_HOUR = 16.5

# --- Speeds ----------------------------------------------------------------
HYPER_SPEED = 8_333.0            # m/s (30,000 km/h) for autopilot hyper mode
EXPRESS_LATERAL = 120_000.0      # m/s max lateral "lane express" speed
GHOST_SPEED = 140.0              # above this speed traffic/collisions are skipped

# --- Phones: draw a bit less so it runs smoothly ---------------------------
if IS_ANDROID:
    BANDS_EACH_SIDE = 2
    CITY_RADIUS_X = 2
    CITY_AHEAD = 4
    CITY_CACHE = 160
    MAX_TRAFFIC = 70
    TRAFFIC_LANES_EACH_SIDE = 12
