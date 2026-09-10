import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite
import chess

from backend.database.db import (
    CURRENT_RATING_MODEL,
    DEFAULT_RATING_POOL,
    connect,
    ensure_competitive_profile,
)


STARTING_FEN = chess.STARTING_FEN

GLICKO2_SCALE = 173.7178
GLICKO2_TAU = 0.5
GLICKO2_EPSILON = 0.000001

MIN_RATING = 100.0
MIN_RD = 30.0
MAX_RD = 350.0

PROVISIONAL_GAMES = 20

STARTING_SR = 2500
MIN_SR = 0

MIN_RATED_RESIGNATION_PLIES = 8
MIN_RATED_RESIGNATION_SECONDS = 30

MAX_RATED_PAIR_GAMES_24H = 3

RISK_REPEAT_PAIR = 20
RISK_FAST_GAME = 20
RISK_REPEAT_RESIGNATIONS = 20


@dataclass
class IntegrityDecision:
    decision: str
    reason: str
    risk_score: int
    events: list[dict]


async def get_user_by_discord_id(
    db,
    discord_id,
):
    cursor = await db.execute(
        """
        SELECT
            id,
            discord_id,
            username,
            display_name,
            avatar_url,
            (SELECT rating FROM skill_ratings WHERE user_id=users.id AND pool='standard') AS chess_rating,
            (SELECT sr FROM progression WHERE user_id=users.id) AS sr
        FROM users
        WHERE discord_id = ?
        """,
        (
            int(discord_id),
        ),
    )

    return await cursor.fetchone()


async def get_user_by_id(
    db,
    user_id,
):
    cursor = await db.execute(
        """
        SELECT
            id,
            discord_id,
            username,
            display_name,
            avatar_url,
            (SELECT rating FROM skill_ratings WHERE user_id=users.id AND pool='standard') AS chess_rating,
            (SELECT sr FROM progression WHERE user_id=users.id) AS sr
        FROM users
        WHERE id = ?
        """,
        (
            user_id,
        ),
    )

    return await cursor.fetchone()


async def get_skill_rating(
    db,
    user_id,
    pool=DEFAULT_RATING_POOL,
):
    await ensure_competitive_profile(
        db,
        user_id,
        commit=False,
    )

    cursor = await db.execute(
        """
        SELECT
            user_id,
            pool,

            rating,
            peak_rating,

            rating_deviation,
            volatility,

            provisional,
            rated_games,

            wins,
            losses,
            draws,

            current_win_streak,
            best_win_streak,

            model_version,
            last_rated_at

        FROM skill_ratings

        WHERE
            user_id = ?
            AND pool = ?
        """,
        (
            user_id,
            pool,
        ),
    )

    return await cursor.fetchone()


async def get_progression(
    db,
    user_id,
):
    await ensure_competitive_profile(
        db,
        user_id,
        commit=False,
    )

    cursor = await db.execute(
        """
        SELECT
            user_id,
            sr,
            peak_sr,
            total_sr_earned,
            games_rewarded
        FROM progression
        WHERE user_id = ?
        """,
        (
            user_id,
        ),
    )

    return await cursor.fetchone()


def serialize_player(row):
    if row is None:
        return None

    return {
        "id": row["id"],
        "discord_id":
            str(
                row["discord_id"]
            ),

        "username":
            row["username"],

        "display_name":
            row["display_name"],

        "avatar_url":
            row["avatar_url"],

        "chess_rating": row["chess_rating"],
        "sr": row["sr"],
    }


def get_user_color(
    game_row,
    user_id,
):
    if (
        game_row["white_user_id"]
        == user_id
    ):
        return "white"

    if (
        game_row["black_user_id"]
        == user_id
    ):
        return "black"

    return "spectator"


def get_user_result(
    game_row,
    user_id,
):
    color = get_user_color(
        game_row,
        user_id,
    )

    status = game_row["status"]

    if status == "waiting":
        return "waiting"

    if status == "active":
        return "in_progress"

    if status == "draw":
        return "draw"

    if status == "white_win":
        return (
            "win"
            if color == "white"
            else "loss"
        )

    if status == "black_win":
        return (
            "win"
            if color == "black"
            else "loss"
        )

    return status


def clamp(
    value,
    minimum,
    maximum,
):
    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


def parse_timestamp(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value)
        )

    except (
        TypeError,
        ValueError,
    ):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def elapsed_seconds(
    start_value,
    end_value=None,
):
    start = parse_timestamp(
        start_value
    )

    if start is None:
        return None

    end = (
        parse_timestamp(
            end_value
        )
        if end_value
        else datetime.now(
            timezone.utc
        )
    )

    if end is None:
        return None

    return max(
        0,
        int(
            (
                end - start
            ).total_seconds()
        ),
    )


def inflate_rd_for_inactivity(
    rating_row,
):
    rd = float(
        rating_row[
            "rating_deviation"
        ]
    )

    volatility = float(
        rating_row[
            "volatility"
        ]
    )

    last_rated_at = (
        parse_timestamp(
            rating_row[
                "last_rated_at"
            ]
        )
    )

    if last_rated_at is None:
        return clamp(
            rd,
            MIN_RD,
            MAX_RD,
        )

    days = max(
        0.0,
        (
            datetime.now(
                timezone.utc
            )
            -
            last_rated_at
        ).total_seconds()
        /
        86400.0,
    )

    if days <= 0:
        return clamp(
            rd,
            MIN_RD,
            MAX_RD,
        )

    phi = (
        rd
        /
        GLICKO2_SCALE
    )

    periods = min(
        days,
        365.0,
    )

    phi_star = math.sqrt(
        phi * phi
        +
        volatility
        *
        volatility
        *
        periods
    )

    return clamp(
        phi_star
        *
        GLICKO2_SCALE,
        MIN_RD,
        MAX_RD,
    )


def glicko_g(phi):
    return (
        1.0
        /
        math.sqrt(
            1.0
            +
            (
                3.0
                *
                phi
                *
                phi
                /
                (
                    math.pi
                    *
                    math.pi
                )
            )
        )
    )


def glicko_expected(
    mu,
    opponent_mu,
    opponent_phi,
):
    exponent = (
        -glicko_g(
            opponent_phi
        )
        *
        (
            mu -
            opponent_mu
        )
    )

    exponent = clamp(
        exponent,
        -700.0,
        700.0,
    )

    return (
        1.0
        /
        (
            1.0
            +
            math.exp(
                exponent
            )
        )
    )


def volatility_function(
    x,
    delta,
    phi,
    variance,
    a,
):
    exp_x = math.exp(x)

    numerator = (
        exp_x
        *
        (
            delta
            *
            delta
            -
            phi
            *
            phi
            -
            variance
            -
            exp_x
        )
    )

    denominator = (
        2.0
        *
        (
            phi
            *
            phi
            +
            variance
            +
            exp_x
        )
        ** 2
    )

    return (
        numerator
        /
        denominator
        -
        (
            x - a
        )
        /
        (
            GLICKO2_TAU
            *
            GLICKO2_TAU
        )
    )


def calculate_new_volatility(
    phi,
    volatility,
    delta,
    variance,
):
    a = math.log(
        volatility
        *
        volatility
    )

    big_a = a

    if (
        delta * delta
        >
        phi * phi
        +
        variance
    ):
        big_b = math.log(
            delta
            *
            delta
            -
            phi
            *
            phi
            -
            variance
        )

    else:
        k = 1

        while True:
            candidate = (
                a
                -
                k
                *
                GLICKO2_TAU
            )

            if (
                volatility_function(
                    candidate,
                    delta,
                    phi,
                    variance,
                    a,
                )
                >= 0
            ):
                big_b = candidate
                break

            k += 1

            if k > 100:
                big_b = candidate
                break

    f_a = volatility_function(
        big_a,
        delta,
        phi,
        variance,
        a,
    )

    f_b = volatility_function(
        big_b,
        delta,
        phi,
        variance,
        a,
    )

    for _ in range(100):
        if (
            abs(
                big_b -
                big_a
            )
            <=
            GLICKO2_EPSILON
        ):
            break

        denominator = (
            f_b -
            f_a
        )

        if (
            abs(
                denominator
            )
            <
            1e-15
        ):
            break

        big_c = (
            big_a
            +
            (
                big_a -
                big_b
            )
            *
            f_a
            /
            denominator
        )

        f_c = volatility_function(
            big_c,
            delta,
            phi,
            variance,
            a,
        )

        if (
            f_c
            *
            f_b
            <
            0
        ):
            big_a = big_b
            f_a = f_b

        else:
            f_a /= 2.0

        big_b = big_c
        f_b = f_c

    return math.exp(
        big_a /
        2.0
    )


def glicko2_update_single_game(
    rating,
    rd,
    volatility,
    opponent_rating,
    opponent_rd,
    score,
):
    mu = (
        float(rating)
        -
        1500.0
    ) / GLICKO2_SCALE

    phi = (
        float(rd)
        /
        GLICKO2_SCALE
    )

    opponent_mu = (
        float(
            opponent_rating
        )
        -
        1500.0
    ) / GLICKO2_SCALE

    opponent_phi = (
        float(
            opponent_rd
        )
        /
        GLICKO2_SCALE
    )

    g_value = glicko_g(
        opponent_phi
    )

    expected = glicko_expected(
        mu,
        opponent_mu,
        opponent_phi,
    )

    variance = (
        1.0
        /
        (
            g_value
            *
            g_value
            *
            expected
            *
            (
                1.0 -
                expected
            )
        )
    )

    delta = (
        variance
        *
        g_value
        *
        (
            score -
            expected
        )
    )

    new_volatility = (
        calculate_new_volatility(
            phi,
            float(volatility),
            delta,
            variance,
        )
    )

    phi_star = math.sqrt(
        phi * phi
        +
        new_volatility
        *
        new_volatility
    )

    new_phi = (
        1.0
        /
        math.sqrt(
            (
                1.0
                /
                (
                    phi_star
                    *
                    phi_star
                )
            )
            +
            (
                1.0
                /
                variance
            )
        )
    )

    new_mu = (
        mu
        +
        new_phi
        *
        new_phi
        *
        g_value
        *
        (
            score -
            expected
        )
    )

    return {
        "rating":
            max(
                MIN_RATING,
                1500.0
                +
                GLICKO2_SCALE
                *
                new_mu,
            ),

        "rd":
            clamp(
                GLICKO2_SCALE
                *
                new_phi,
                MIN_RD,
                MAX_RD,
            ),

        "volatility":
            new_volatility,

        "expected":
            expected,
    }


def calculate_sr_change(
    *,
    result,
    player_rating,
    opponent_rating,
    current_streak,
):
    rating_gap = (
        opponent_rating
        -
        player_rating
    )

    strength_bonus = int(
        clamp(
            round(
                rating_gap /
                20.0
            ),
            -20,
            40,
        )
    )

    if result == "win":
        streak_bonus = min(
            max(
                current_streak,
                0,
            )
            *
            5,
            25,
        )

        return max(
            40,
            100
            +
            strength_bonus
            +
            streak_bonus,
        )

    if result == "draw":
        return max(
            0,
            20
            +
            int(
                clamp(
                    round(
                        rating_gap /
                        30.0
                    ),
                    -15,
                    20,
                )
            ),
        )

    loss_relief = int(
        clamp(
            round(
                rating_gap /
                25.0
            ),
            -20,
            20,
        )
    )

    return min(
        -10,
        -35
        +
        loss_relief,
    )


async def get_move_count(
    db,
    game_id,
):
    cursor = await db.execute(
        """
        SELECT
            COUNT(*) AS count
        FROM game_moves
        WHERE game_id = ?
        """,
        (
            game_id,
        ),
    )

    row = await cursor.fetchone()

    return int(
        row["count"]
        if row
        else 0
    )


async def get_recent_pair_approved_count(
    db,
    user_a,
    user_b,
):
    cursor = await db.execute(
        """
        SELECT
            COUNT(*) AS count

        FROM competitive_transactions

        WHERE
            decision = 'approved'
            AND reversed = 0

            AND created_at >=
                datetime(
                    'now',
                    '-24 hours'
                )

            AND (
                (
                    white_user_id = ?
                    AND
                    black_user_id = ?
                )

                OR

                (
                    white_user_id = ?
                    AND
                    black_user_id = ?
                )
            )
        """,
        (
            user_a,
            user_b,
            user_b,
            user_a,
        ),
    )

    row = await cursor.fetchone()

    return int(
        row["count"]
        if row
        else 0
    )


async def get_recent_pair_resignations(
    db,
    user_a,
    user_b,
):
    cursor = await db.execute(
        """
        SELECT
            COUNT(*) AS count

        FROM games

        WHERE
            termination_reason =
                'resignation'

            AND completed_at >=
                datetime(
                    'now',
                    '-24 hours'
                )

            AND (
                (
                    white_user_id = ?
                    AND
                    black_user_id = ?
                )

                OR

                (
                    white_user_id = ?
                    AND
                    black_user_id = ?
                )
            )
        """,
        (
            user_a,
            user_b,
            user_b,
            user_a,
        ),
    )

    row = await cursor.fetchone()

    return int(
        row["count"]
        if row
        else 0
    )


async def record_integrity_event(
    db,
    *,
    game_id,
    user_id,
    code,
    severity,
    risk_points,
    details,
):
    await db.execute(
        """
        INSERT INTO integrity_events (
            game_id,
            user_id,
            code,
            severity,
            risk_points,
            details_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            user_id,
            code,
            severity,
            int(
                risk_points
            ),
            json.dumps(
                details,
                separators=(
                    ",",
                    ":",
                ),
            ),
        ),
    )


async def evaluate_integrity(
    db,
    game_row,
):
    events = []
    risk = 0

    white_id = (
        game_row[
            "white_user_id"
        ]
    )

    black_id = (
        game_row[
            "black_user_id"
        ]
    )

    if (
        white_id is None
        or
        black_id is None
    ):
        return IntegrityDecision(
            "rejected",
            "missing_player",
            100,
            events,
        )

    if white_id == black_id:
        return IntegrityDecision(
            "rejected",
            "self_play",
            100,
            events,
        )

    if (
        int(
            game_row[
                "rated_eligible"
            ]
            or 0
        )
        != 1
    ):
        return IntegrityDecision(
            "rejected",
            "game_marked_unrated",
            0,
            events,
        )

    if (
        game_row["mode"]
        != "casual"
    ):
        return IntegrityDecision(
            "rejected",
            "unrated_mode",
            0,
            events,
        )

    if (
        game_row["status"]
        not in {
            "white_win",
            "black_win",
            "draw",
        }
    ):
        return IntegrityDecision(
            "rejected",
            "game_not_completed",
            100,
            events,
        )

    move_count = (
        await get_move_count(
            db,
            game_row["id"],
        )
    )

    duration = elapsed_seconds(
        game_row["started_at"],
        game_row["completed_at"],
    )

    if (
        game_row[
            "termination_reason"
        ]
        ==
        "resignation"
    ):
        if (
            move_count
            <
            MIN_RATED_RESIGNATION_PLIES
        ):
            events.append(
                {
                    "code":
                        "early_resignation",

                    "severity":
                        "high",

                    "risk_points":
                        100,

                    "details": {
                        "move_count":
                            move_count,
                    },
                }
            )

            return IntegrityDecision(
                "rejected",
                "early_resignation",
                100,
                events,
            )

        if (
            duration is not None
            and
            duration
            <
            MIN_RATED_RESIGNATION_SECONDS
        ):
            events.append(
                {
                    "code":
                        "rapid_resignation",

                    "severity":
                        "high",

                    "risk_points":
                        100,

                    "details": {
                        "duration_seconds":
                            duration,

                        "move_count":
                            move_count,
                    },
                }
            )

            return IntegrityDecision(
                "rejected",
                "rapid_resignation",
                100,
                events,
            )

    pair_count = (
        await get_recent_pair_approved_count(
            db,
            white_id,
            black_id,
        )
    )

    if (
        pair_count
        >=
        MAX_RATED_PAIR_GAMES_24H
    ):
        events.append(
            {
                "code":
                    "pair_daily_rating_limit",

                "severity":
                    "high",

                "risk_points":
                    100,

                "details": {
                    "approved_pair_games_24h":
                        pair_count,
                },
            }
        )

        return IntegrityDecision(
            "rejected",
            "pair_daily_rating_limit",
            100,
            events,
        )

    if pair_count >= 2:
        risk += (
            RISK_REPEAT_PAIR
        )

        events.append(
            {
                "code":
                    "repeat_pair",

                "severity":
                    "low",

                "risk_points":
                    RISK_REPEAT_PAIR,

                "details": {
                    "approved_pair_games_24h":
                        pair_count,
                },
            }
        )

    if (
        duration is not None
        and
        duration < 60
        and
        move_count < 16
    ):
        risk += (
            RISK_FAST_GAME
        )

        events.append(
            {
                "code":
                    "fast_completed_game",

                "severity":
                    "low",

                "risk_points":
                    RISK_FAST_GAME,

                "details": {
                    "duration_seconds":
                        duration,

                    "move_count":
                        move_count,
                },
            }
        )

    resignation_count = (
        await get_recent_pair_resignations(
            db,
            white_id,
            black_id,
        )
    )

    if resignation_count >= 2:
        risk += (
            RISK_REPEAT_RESIGNATIONS
        )

        events.append(
            {
                "code":
                    "repeat_pair_resignations",

                "severity":
                    "medium",

                "risk_points":
                    RISK_REPEAT_RESIGNATIONS,

                "details": {
                    "pair_resignations_24h":
                        resignation_count,
                },
            }
        )

    return IntegrityDecision(
        "approved",
        "integrity_checks_passed",
        min(
            risk,
            100,
        ),
        events,
    )


async def get_move_history(
    db,
    game_id,
):
    cursor = await db.execute(
        """
        SELECT
            gm.move_number,
            gm.ply,
            gm.color,
            gm.uci,
            gm.san,
            gm.fen_after,
            gm.created_at,

            u.discord_id,
            u.username,
            u.display_name

        FROM game_moves gm

        JOIN users u
            ON u.id =
                gm.user_id

        WHERE
            gm.game_id = ?

        ORDER BY
            gm.ply ASC
        """,
        (
            game_id,
        ),
    )

    rows = await cursor.fetchall()

    return [
        {
            "move_number":
                row[
                    "move_number"
                ],

            "ply":
                row["ply"],

            "color":
                row["color"],

            "uci":
                row["uci"],

            "san":
                row["san"],

            "fen_after":
                row["fen_after"],

            "created_at":
                row["created_at"],

            "player": {
                "discord_id":
                    str(
                        row[
                            "discord_id"
                        ]
                    ),

                "username":
                    row[
                        "username"
                    ],

                "display_name":
                    row[
                        "display_name"
                    ],
            },
        }
        for row in rows
    ]


async def get_competitive_transaction(
    db,
    game_id,
):
    cursor = await db.execute(
        """
        SELECT *
        FROM competitive_transactions
        WHERE game_id = ?
        """,
        (
            game_id,
        ),
    )

    return await cursor.fetchone()


def display_number(value):
    if value is None:
        return None

    return int(
        round(
            float(value)
        )
    )


async def build_game_payload(
    db,
    game_row,
):
    white_user = (
        await get_user_by_id(
            db,
            game_row[
                "white_user_id"
            ],
        )
        if
        game_row[
            "white_user_id"
        ]
        else
        None
    )

    black_user = (
        await get_user_by_id(
            db,
            game_row[
                "black_user_id"
            ],
        )
        if
        game_row[
            "black_user_id"
        ]
        else
        None
    )

    moves = (
        await get_move_history(
            db,
            game_row["id"],
        )
    )

    transaction = (
        await get_competitive_transaction(
            db,
            game_row["id"],
        )
    )

    board = chess.Board(
        game_row[
            "current_fen"
        ]
    )

    competitive = None

    if transaction is not None:
        competitive = {
            "decision":
                transaction[
                    "decision"
                ],

            "decision_reason":
                transaction[
                    "decision_reason"
                ],

            "risk_score":
                transaction[
                    "risk_score"
                ],

            "pool":
                transaction[
                    "pool"
                ],

            "rating_model":
                transaction[
                    "rating_model"
                ],

            "white": {
                "rating_before":
                    display_number(
                        transaction[
                            "white_rating_before"
                        ]
                    ),

                "rating_after":
                    display_number(
                        transaction[
                            "white_rating_after"
                        ]
                    ),

                "rating_change":
                    display_number(
                        transaction[
                            "white_rating_change"
                        ]
                    ),

                "rating_before_precise":
                    transaction[
                        "white_rating_before"
                    ],

                "rating_after_precise":
                    transaction[
                        "white_rating_after"
                    ],

                "rating_change_precise":
                    transaction[
                        "white_rating_change"
                    ],

                "rd_before":
                    round(
                        float(
                            transaction[
                                "white_rd_before"
                            ]
                        ),
                        2,
                    ),

                "rd_after":
                    round(
                        float(
                            transaction[
                                "white_rd_after"
                            ]
                        ),
                        2,
                    ),

                "sr_before":
                    transaction[
                        "white_sr_before"
                    ],

                "sr_after":
                    transaction[
                        "white_sr_after"
                    ],

                "sr_change":
                    transaction[
                        "white_sr_change"
                    ],
            },

            "black": {
                "rating_before":
                    display_number(
                        transaction[
                            "black_rating_before"
                        ]
                    ),

                "rating_after":
                    display_number(
                        transaction[
                            "black_rating_after"
                        ]
                    ),

                "rating_change":
                    display_number(
                        transaction[
                            "black_rating_change"
                        ]
                    ),

                "rating_before_precise":
                    transaction[
                        "black_rating_before"
                    ],

                "rating_after_precise":
                    transaction[
                        "black_rating_after"
                    ],

                "rating_change_precise":
                    transaction[
                        "black_rating_change"
                    ],

                "rd_before":
                    round(
                        float(
                            transaction[
                                "black_rd_before"
                            ]
                        ),
                        2,
                    ),

                "rd_after":
                    round(
                        float(
                            transaction[
                                "black_rd_after"
                            ]
                        ),
                        2,
                    ),

                "sr_before":
                    transaction[
                        "black_sr_before"
                    ],

                "sr_after":
                    transaction[
                        "black_sr_after"
                    ],

                "sr_change":
                    transaction[
                        "black_sr_change"
                    ],
            },
        }

    rating = {
        "white_before":
            display_number(
                game_row[
                    "white_rating_before"
                ]
            ),

        "white_after":
            display_number(
                game_row[
                    "white_rating_after"
                ]
            ),

        "white_change":
            display_number(
                game_row[
                    "white_rating_change"
                ]
            ),

        "white_rd_before":
            game_row[
                "white_rd_before"
            ],

        "white_rd_after":
            game_row[
                "white_rd_after"
            ],

        "black_before":
            display_number(
                game_row[
                    "black_rating_before"
                ]
            ),

        "black_after":
            display_number(
                game_row[
                    "black_rating_after"
                ]
            ),

        "black_change":
            display_number(
                game_row[
                    "black_rating_change"
                ]
            ),

        "black_rd_before":
            game_row[
                "black_rd_before"
            ],

        "black_rd_after":
            game_row[
                "black_rd_after"
            ],
    }

    return {
        "starting_fen": game_row["starting_fen"],
        "game_id":
            game_row[
                "public_id"
            ],

        "mode":
            game_row[
                "mode"
            ],

        "rating_pool":
            game_row[
                "rating_pool"
            ],

        "status":
            game_row[
                "status"
            ],

        "fen":
            game_row[
                "current_fen"
            ],

        "turn":
            (
                "white"
                if board.turn
                else "black"
            ),

        "white":
            serialize_player(
                white_user
            ),

        "black":
            serialize_player(
                black_user
            ),

        "result":
            game_row[
                "result"
            ],

        "termination_reason":
            game_row[
                "termination_reason"
            ],

        "rated_eligible":
            bool(
                game_row[
                    "rated_eligible"
                ]
            ),

        "rating_processed":
            bool(
                game_row[
                    "rating_processed"
                ]
            ),

        "rating":
            rating,

        "competitive":
            competitive,

        "moves":
            moves,

        "created_at":
            game_row[
                "created_at"
            ],

        "started_at":
            game_row[
                "started_at"
            ],

        "updated_at":
            game_row[
                "updated_at"
            ],

        "completed_at":
            game_row[
                "completed_at"
            ],
    }


async def insert_transaction(
    db,
    *,
    game_row,
    decision,
    reason,
    risk_score,

    white_rating_before,
    white_rating_after,
    white_rd_before,
    white_rd_after,
    white_volatility_before,
    white_volatility_after,

    black_rating_before,
    black_rating_after,
    black_rd_before,
    black_rd_after,
    black_volatility_before,
    black_volatility_after,

    white_sr_before,
    white_sr_after,

    black_sr_before,
    black_sr_after,
):
    await db.execute(
        """
        INSERT INTO competitive_transactions (
            game_id,

            pool,
            rating_model,

            decision,
            decision_reason,
            risk_score,

            white_user_id,
            black_user_id,

            white_rating_before,
            white_rating_after,
            white_rating_change,

            white_rd_before,
            white_rd_after,

            white_volatility_before,
            white_volatility_after,

            black_rating_before,
            black_rating_after,
            black_rating_change,

            black_rd_before,
            black_rd_after,

            black_volatility_before,
            black_volatility_after,

            white_sr_before,
            white_sr_after,
            white_sr_change,

            black_sr_before,
            black_sr_after,
            black_sr_change,

            result
        )

        VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?
        )
        """,
        (
            game_row["id"],

            game_row[
                "rating_pool"
            ],

            CURRENT_RATING_MODEL,

            decision,
            reason,
            int(
                risk_score
            ),

            game_row[
                "white_user_id"
            ],

            game_row[
                "black_user_id"
            ],

            white_rating_before,
            white_rating_after,

            (
                white_rating_after
                -
                white_rating_before
            ),

            white_rd_before,
            white_rd_after,

            white_volatility_before,
            white_volatility_after,

            black_rating_before,
            black_rating_after,

            (
                black_rating_after
                -
                black_rating_before
            ),

            black_rd_before,
            black_rd_after,

            black_volatility_before,
            black_volatility_after,

            white_sr_before,
            white_sr_after,

            (
                white_sr_after
                -
                white_sr_before
            ),

            black_sr_before,
            black_sr_after,

            (
                black_sr_after
                -
                black_sr_before
            ),

            game_row[
                "result"
            ],
        ),
    )


async def process_competitive_result(
    db,
    game_id,
):
    await db.execute(
        "BEGIN IMMEDIATE"
    )

    try:
        cursor = await db.execute(
            """
            SELECT *
            FROM games
            WHERE id = ?
            """,
            (
                game_id,
            ),
        )

        game = await cursor.fetchone()

        if game is None:
            await db.rollback()
            return

        if (
            int(
                game[
                    "rating_processed"
                ]
                or 0
            )
            ==
            1
        ):
            await db.commit()
            return

        if (
            game[
                "white_user_id"
            ]
            is None
            or
            game[
                "black_user_id"
            ]
            is None
        ):
            await db.rollback()
            return

        white_rating = (
            await get_skill_rating(
                db,
                game[
                    "white_user_id"
                ],
                game[
                    "rating_pool"
                ],
            )
        )

        black_rating = (
            await get_skill_rating(
                db,
                game[
                    "black_user_id"
                ],
                game[
                    "rating_pool"
                ],
            )
        )

        white_progress = (
            await get_progression(
                db,
                game[
                    "white_user_id"
                ],
            )
        )

        black_progress = (
            await get_progression(
                db,
                game[
                    "black_user_id"
                ],
            )
        )

        decision = (
            await evaluate_integrity(
                db,
                game,
            )
        )

        for event in decision.events:
            await record_integrity_event(
                db,

                game_id=
                    game["id"],

                user_id=
                    None,

                code=
                    event["code"],

                severity=
                    event[
                        "severity"
                    ],

                risk_points=
                    event[
                        "risk_points"
                    ],

                details=
                    event[
                        "details"
                    ],
            )

        white_before = float(
            white_rating[
                "rating"
            ]
        )

        black_before = float(
            black_rating[
                "rating"
            ]
        )

        white_rd_before = (
            inflate_rd_for_inactivity(
                white_rating
            )
        )

        black_rd_before = (
            inflate_rd_for_inactivity(
                black_rating
            )
        )

        white_vol_before = float(
            white_rating[
                "volatility"
            ]
        )

        black_vol_before = float(
            black_rating[
                "volatility"
            ]
        )

        white_sr_before = int(
            white_progress[
                "sr"
            ]
        )

        black_sr_before = int(
            black_progress[
                "sr"
            ]
        )

        if (
            decision.decision
            !=
            "approved"
        ):
            await insert_transaction(
                db,

                game_row=
                    game,

                decision=
                    decision.decision,

                reason=
                    decision.reason,

                risk_score=
                    decision.risk_score,

                white_rating_before=
                    white_before,

                white_rating_after=
                    white_before,

                white_rd_before=
                    white_rd_before,

                white_rd_after=
                    white_rd_before,

                white_volatility_before=
                    white_vol_before,

                white_volatility_after=
                    white_vol_before,

                black_rating_before=
                    black_before,

                black_rating_after=
                    black_before,

                black_rd_before=
                    black_rd_before,

                black_rd_after=
                    black_rd_before,

                black_volatility_before=
                    black_vol_before,

                black_volatility_after=
                    black_vol_before,

                white_sr_before=
                    white_sr_before,

                white_sr_after=
                    white_sr_before,

                black_sr_before=
                    black_sr_before,

                black_sr_after=
                    black_sr_before,
            )

            await db.execute(
                """
                UPDATE games

                SET
                    rating_processed = 1,

                    rating_model = ?,

                    integrity_status = ?,
                    integrity_reason = ?,
                    integrity_risk_score = ?,

                    white_rating_before = ?,
                    white_rating_after = ?,
                    white_rating_change = 0,

                    black_rating_before = ?,
                    black_rating_after = ?,
                    black_rating_change = 0,

                    white_rd_before = ?,
                    white_rd_after = ?,

                    black_rd_before = ?,
                    black_rd_after = ?

                WHERE
                    id = ?
                    AND rating_processed = 0
                """,
                (
                    CURRENT_RATING_MODEL,

                    decision.decision,
                    decision.reason,
                    decision.risk_score,

                    white_before,
                    white_before,

                    black_before,
                    black_before,

                    white_rd_before,
                    white_rd_before,

                    black_rd_before,
                    black_rd_before,

                    game["id"],
                ),
            )

            await db.commit()
            return

        if (
            game["status"]
            ==
            "white_win"
        ):
            white_score = 1.0
            black_score = 0.0

            white_result = "win"
            black_result = "loss"

        elif (
            game["status"]
            ==
            "black_win"
        ):
            white_score = 0.0
            black_score = 1.0

            white_result = "loss"
            black_result = "win"

        else:
            white_score = 0.5
            black_score = 0.5

            white_result = "draw"
            black_result = "draw"

        white_update = (
            glicko2_update_single_game(
                white_before,
                white_rd_before,
                white_vol_before,

                black_before,
                black_rd_before,

                white_score,
            )
        )

        black_update = (
            glicko2_update_single_game(
                black_before,
                black_rd_before,
                black_vol_before,

                white_before,
                white_rd_before,

                black_score,
            )
        )

        white_after = float(
            white_update[
                "rating"
            ]
        )

        black_after = float(
            black_update[
                "rating"
            ]
        )

        white_rd_after = float(
            white_update[
                "rd"
            ]
        )

        black_rd_after = float(
            black_update[
                "rd"
            ]
        )

        white_vol_after = float(
            white_update[
                "volatility"
            ]
        )

        black_vol_after = float(
            black_update[
                "volatility"
            ]
        )

        white_sr_change = (
            calculate_sr_change(
                result=
                    white_result,

                player_rating=
                    white_before,

                opponent_rating=
                    black_before,

                current_streak=
                    int(
                        white_rating[
                            "current_win_streak"
                        ]
                    ),
            )
        )

        black_sr_change = (
            calculate_sr_change(
                result=
                    black_result,

                player_rating=
                    black_before,

                opponent_rating=
                    white_before,

                current_streak=
                    int(
                        black_rating[
                            "current_win_streak"
                        ]
                    ),
            )
        )

        white_sr_after = max(
            MIN_SR,

            white_sr_before
            +
            white_sr_change,
        )

        black_sr_after = max(
            MIN_SR,

            black_sr_before
            +
            black_sr_change,
        )

        if white_result == "win":
            white_w = 1
            white_l = 0
            white_d = 0

            black_w = 0
            black_l = 1
            black_d = 0

            white_streak = (
                int(
                    white_rating[
                        "current_win_streak"
                    ]
                )
                +
                1
            )

            black_streak = 0

        elif black_result == "win":
            white_w = 0
            white_l = 1
            white_d = 0

            black_w = 1
            black_l = 0
            black_d = 0

            white_streak = 0

            black_streak = (
                int(
                    black_rating[
                        "current_win_streak"
                    ]
                )
                +
                1
            )

        else:
            white_w = 0
            white_l = 0
            white_d = 1

            black_w = 0
            black_l = 0
            black_d = 1

            white_streak = 0
            black_streak = 0

        white_best = max(
            int(
                white_rating[
                    "best_win_streak"
                ]
            ),
            white_streak,
        )

        black_best = max(
            int(
                black_rating[
                    "best_win_streak"
                ]
            ),
            black_streak,
        )

        white_rated_games = (
            int(
                white_rating[
                    "rated_games"
                ]
            )
            +
            1
        )

        black_rated_games = (
            int(
                black_rating[
                    "rated_games"
                ]
            )
            +
            1
        )

        white_provisional = (
            1
            if
            white_rated_games
            <
            PROVISIONAL_GAMES
            else
            0
        )

        black_provisional = (
            1
            if
            black_rated_games
            <
            PROVISIONAL_GAMES
            else
            0
        )

        await db.execute(
            """
            UPDATE skill_ratings

            SET
                rating = ?,

                peak_rating =
                    MAX(
                        peak_rating,
                        ?
                    ),

                rating_deviation = ?,
                volatility = ?,

                provisional = ?,

                rated_games =
                    rated_games + 1,

                wins =
                    wins + ?,

                losses =
                    losses + ?,

                draws =
                    draws + ?,

                current_win_streak = ?,
                best_win_streak = ?,

                model_version = ?,

                last_rated_at =
                    CURRENT_TIMESTAMP,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE
                user_id = ?
                AND pool = ?
            """,
            (
                white_after,
                white_after,

                white_rd_after,
                white_vol_after,

                white_provisional,

                white_w,
                white_l,
                white_d,

                white_streak,
                white_best,

                CURRENT_RATING_MODEL,

                game[
                    "white_user_id"
                ],

                game[
                    "rating_pool"
                ],
            ),
        )

        await db.execute(
            """
            UPDATE skill_ratings

            SET
                rating = ?,

                peak_rating =
                    MAX(
                        peak_rating,
                        ?
                    ),

                rating_deviation = ?,
                volatility = ?,

                provisional = ?,

                rated_games =
                    rated_games + 1,

                wins =
                    wins + ?,

                losses =
                    losses + ?,

                draws =
                    draws + ?,

                current_win_streak = ?,
                best_win_streak = ?,

                model_version = ?,

                last_rated_at =
                    CURRENT_TIMESTAMP,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE
                user_id = ?
                AND pool = ?
            """,
            (
                black_after,
                black_after,

                black_rd_after,
                black_vol_after,

                black_provisional,

                black_w,
                black_l,
                black_d,

                black_streak,
                black_best,

                CURRENT_RATING_MODEL,

                game[
                    "black_user_id"
                ],

                game[
                    "rating_pool"
                ],
            ),
        )

        await db.execute(
            """
            UPDATE progression

            SET
                sr = ?,

                peak_sr =
                    MAX(
                        peak_sr,
                        ?
                    ),

                total_sr_earned =
                    total_sr_earned
                    +
                    ?,

                games_rewarded =
                    games_rewarded
                    +
                    1,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE user_id = ?
            """,
            (
                white_sr_after,
                white_sr_after,

                max(
                    0,
                    white_sr_change,
                ),

                game[
                    "white_user_id"
                ],
            ),
        )

        await db.execute(
            """
            UPDATE progression

            SET
                sr = ?,

                peak_sr =
                    MAX(
                        peak_sr,
                        ?
                    ),

                total_sr_earned =
                    total_sr_earned
                    +
                    ?,

                games_rewarded =
                    games_rewarded
                    +
                    1,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE user_id = ?
            """,
            (
                black_sr_after,
                black_sr_after,

                max(
                    0,
                    black_sr_change,
                ),

                game[
                    "black_user_id"
                ],
            ),
        )

        await insert_transaction(
            db,

            game_row=
                game,

            decision=
                "approved",

            reason=
                "integrity_checks_passed",

            risk_score=
                decision.risk_score,

            white_rating_before=
                white_before,

            white_rating_after=
                white_after,

            white_rd_before=
                white_rd_before,

            white_rd_after=
                white_rd_after,

            white_volatility_before=
                white_vol_before,

            white_volatility_after=
                white_vol_after,

            black_rating_before=
                black_before,

            black_rating_after=
                black_after,

            black_rd_before=
                black_rd_before,

            black_rd_after=
                black_rd_after,

            black_volatility_before=
                black_vol_before,

            black_volatility_after=
                black_vol_after,

            white_sr_before=
                white_sr_before,

            white_sr_after=
                white_sr_after,

            black_sr_before=
                black_sr_before,

            black_sr_after=
                black_sr_after,
        )

        await db.execute(
            """
            UPDATE games

            SET
                rating_processed = 1,

                rating_model = ?,

                integrity_status =
                    'approved',

                integrity_reason =
                    'integrity_checks_passed',

                integrity_risk_score = ?,

                white_rating_before = ?,
                white_rating_after = ?,
                white_rating_change = ?,

                black_rating_before = ?,
                black_rating_after = ?,
                black_rating_change = ?,

                white_rd_before = ?,
                white_rd_after = ?,

                black_rd_before = ?,
                black_rd_after = ?

            WHERE
                id = ?
                AND
                rating_processed = 0
            """,
            (
                CURRENT_RATING_MODEL,

                decision.risk_score,

                white_before,
                white_after,

                (
                    white_after
                    -
                    white_before
                ),

                black_before,
                black_after,

                (
                    black_after
                    -
                    black_before
                ),

                white_rd_before,
                white_rd_after,

                black_rd_before,
                black_rd_after,

                game["id"],
            ),
        )

        await db.commit()

    except Exception:
        await db.rollback()
        raise


async def finalize_game(
    db,
    game_id,
    status,
    result,
    termination_reason,
    current_fen=None,
):
    if current_fen is None:
        await db.execute(
            """
            UPDATE games

            SET
                status = ?,
                result = ?,

                termination_reason = ?,

                completed_at =
                    CURRENT_TIMESTAMP,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE
                id = ?
                AND
                status = 'active'
            """,
            (
                status,
                result,
                termination_reason,
                game_id,
            ),
        )

    else:
        await db.execute(
            """
            UPDATE games

            SET
                current_fen = ?,

                status = ?,
                result = ?,

                termination_reason = ?,

                completed_at =
                    CURRENT_TIMESTAMP,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE
                id = ?
                AND
                status = 'active'
            """,
            (
                current_fen,

                status,
                result,

                termination_reason,

                game_id,
            ),
        )

    await db.commit()

    await process_competitive_result(
        db,
        game_id,
    )

    cursor = await db.execute(
        """
        SELECT *
        FROM games
        WHERE id = ?
        """,
        (
            game_id,
        ),
    )

    return await cursor.fetchone()


async def create_casual_game(
    creator_discord_id,
):
    db = await connect()

    try:
        creator = (
            await get_user_by_discord_id(
                db,
                creator_discord_id,
            )
        )

        if creator is None:
            return {
                "ok": False,
                "error":
                    "user_not_found",
            }

        await ensure_competitive_profile(
            db,
            creator["id"],
        )

        public_id = str(
            uuid.uuid4()
        )

        insert_sql = """
            INSERT INTO games (
                public_id,

                white_user_id,
                black_user_id,

                mode,
                rating_pool,

                status,

                starting_fen,
                current_fen,

                rated_eligible,

                integrity_status,

                rating_model
            )

            VALUES (
                ?,
                ?,
                NULL,

                'casual',
                ?,

                'waiting',

                ?,
                ?,

                1,

                'pending',

                ?
            )
            """
        if getattr(db, "backend", "sqlite") == "postgres":
            insert_sql = insert_sql.rstrip() + " RETURNING id"
        cursor = await db.execute(
            insert_sql,
            (
                public_id,

                creator["id"],

                DEFAULT_RATING_POOL,

                STARTING_FEN,
                STARTING_FEN,

                CURRENT_RATING_MODEL,
            ),
        )

        if getattr(db, "backend", "sqlite") == "postgres":
            inserted = await cursor.fetchone()
            game_id = inserted["id"]
        else:
            game_id = cursor.lastrowid
        await db.commit()

        cursor = await db.execute(
            """
            SELECT *
            FROM games
            WHERE id = ?
            """,
            (
                game_id,
            ),
        )

        row = await cursor.fetchone()

        return {
            "ok": True,

            "game":
                await build_game_payload(
                    db,
                    row,
                ),
        }

    finally:
        await db.close()

async def create_private_game_for_user(user_id):
    """Create a private waiting game for any canonical Bishoply account."""
    db = await connect()
    try:
        user = await get_user_by_id(db, user_id)
        if user is None: return {"ok": False, "error": "user_not_found"}
        await ensure_competitive_profile(db, user_id)
        public_id = uuid.uuid4().hex[:10].upper()
        sql = "INSERT INTO games(public_id,white_user_id,black_user_id,mode,rating_pool,status,starting_fen,current_fen,rated_eligible,integrity_status,rating_model) VALUES (?,?,NULL,'private',?,'waiting',?,?,1,'pending',?)"
        if getattr(db, "backend", "sqlite") == "postgres": sql += " RETURNING id"
        cursor = await db.execute(sql, (public_id, user_id, DEFAULT_RATING_POOL, STARTING_FEN, STARTING_FEN, CURRENT_RATING_MODEL))
        game_id = (await cursor.fetchone())["id"] if getattr(db, "backend", "sqlite") == "postgres" else cursor.lastrowid
        await db.commit(); row = await (await db.execute("SELECT * FROM games WHERE id=?", (game_id,))).fetchone()
        return {"ok": True, "game": await build_game_payload(db, row), "code": public_id}
    finally: await db.close()

async def join_private_game_for_user(public_id, user_id):
    db = await connect()
    try:
        await db.execute("BEGIN IMMEDIATE") if getattr(db, "backend", "sqlite") != "postgres" else None
        select_sql = "SELECT * FROM games WHERE public_id=?" + (" FOR UPDATE" if getattr(db, "backend", "sqlite") == "postgres" else "")
        game = await (await db.execute(select_sql, (public_id,))).fetchone()
        if not game: return {"ok": False, "error": "game_not_found"}
        if game["white_user_id"] == user_id: return {"ok": False, "error": "cannot_join_own_game"}
        if game["black_user_id"] is not None: return {"ok": False, "error": "game_full"}
        await db.execute("UPDATE games SET black_user_id=?,status='active',started_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=? AND black_user_id IS NULL", (user_id, game["id"]))
        await db.commit(); game = await (await db.execute("SELECT * FROM games WHERE id=?", (game["id"],))).fetchone()
        return {"ok": True, "game": await build_game_payload(db, game)}
    except Exception:
        await db.rollback(); raise
    finally: await db.close()


async def join_casual_game(
    public_id,
    discord_id,
):
    db = await connect()

    try:
        user = (
            await get_user_by_discord_id(
                db,
                discord_id,
            )
        )

        if user is None:
            return {
                "ok": False,
                "error":
                    "user_not_found",
            }

        await ensure_competitive_profile(
            db,
            user["id"],
        )

        cursor = await db.execute(
            """
            SELECT *
            FROM games
            WHERE public_id = ?
            """,
            (
                public_id,
            ),
        )

        game = await cursor.fetchone()

        if game is None:
            return {
                "ok": False,
                "error":
                    "game_not_found",
            }

        if (
            game[
                "white_user_id"
            ]
            ==
            user["id"]
        ):
            return {
                "ok": False,
                "error":
                    "cannot_join_own_game",
            }

        if (
            game[
                "black_user_id"
            ]
            ==
            user["id"]
        ):
            return {
                "ok": True,

                "game":
                    await build_game_payload(
                        db,
                        game,
                    ),
            }

        if (
            game[
                "black_user_id"
            ]
            is not None
        ):
            return {
                "ok": False,
                "error":
                    "game_full",
            }

        if (
            game["status"]
            != "waiting"
        ):
            return {
                "ok": False,
                "error":
                    "game_not_joinable",
            }

        cursor = await db.execute(
            """
            UPDATE games

            SET
                black_user_id = ?,

                status =
                    'active',

                started_at =
                    CURRENT_TIMESTAMP,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE
                id = ?

                AND
                status =
                    'waiting'

                AND
                black_user_id
                    IS NULL
            """,
            (
                user["id"],
                game["id"],
            ),
        )

        await db.commit()

        if cursor.rowcount != 1:
            return {
                "ok": False,
                "error":
                    "game_full",
            }

        cursor = await db.execute(
            """
            SELECT *
            FROM games
            WHERE id = ?
            """,
            (
                game["id"],
            ),
        )

        updated = (
            await cursor.fetchone()
        )

        return {
            "ok": True,

            "game":
                await build_game_payload(
                    db,
                    updated,
                ),
        }

    finally:
        await db.close()


async def get_game(
    public_id,
):
    db = await connect()

    try:
        cursor = await db.execute(
            """
            SELECT *
            FROM games
            WHERE public_id = ?
            """,
            (
                public_id,
            ),
        )

        game = await cursor.fetchone()

        if game is None:
            return {
                "ok": False,
                "error":
                    "game_not_found",
            }

        return {
            "ok": True,

            "game":
                await build_game_payload(
                    db,
                    game,
                ),
        }

    finally:
        await db.close()


async def resign_game(
    public_id,
    discord_id,
):
    db = await connect()

    try:
        user = (
            await get_user_by_discord_id(
                db,
                discord_id,
            )
        )

        if user is None:
            return {
                "ok": False,
                "error":
                    "user_not_found",
            }

        cursor = await db.execute(
            """
            SELECT *
            FROM games
            WHERE public_id = ?
            """,
            (
                public_id,
            ),
        )

        game = await cursor.fetchone()

        if game is None:
            return {
                "ok": False,
                "error":
                    "game_not_found",
            }

        if (
            game["status"]
            != "active"
        ):
            return {
                "ok": False,
                "error":
                    "game_not_active",
            }

        if (
            user["id"]
            ==
            game[
                "white_user_id"
            ]
        ):
            status = "black_win"
            result = "0-1"

        elif (
            user["id"]
            ==
            game[
                "black_user_id"
            ]
        ):
            status = "white_win"
            result = "1-0"

        else:
            return {
                "ok": False,
                "error":
                    "not_a_player",
            }

        updated = (
            await finalize_game(
                db,

                game["id"],

                status,
                result,

                "resignation",
            )
        )

        return {
            "ok": True,

            "game":
                await build_game_payload(
                    db,
                    updated,
                ),
        }

    finally:
        await db.close()


async def list_user_games(
    discord_id,
    limit=25,
    offset=0,
):
    db = await connect()

    try:
        user = (
            await get_user_by_discord_id(
                db,
                discord_id,
            )
        )

        if user is None:
            return {
                "ok": False,
                "error":
                    "user_not_found",
            }

        safe_limit = max(
            1,
            min(
                int(limit),
                100,
            ),
        )
        safe_offset = max(0, min(int(offset), 100000))

        cursor = await db.execute(
            """
            SELECT
                g.*,

                white.discord_id
                    AS white_discord_id,

                white.username
                    AS white_username,

                white.display_name
                    AS white_display_name,

                white.avatar_url
                    AS white_avatar_url,

                black.discord_id
                    AS black_discord_id,

                black.username
                    AS black_username,

                black.display_name
                    AS black_display_name,

                black.avatar_url
                    AS black_avatar_url,

                gm.move_count,

                gm.last_move_at,

                ct.decision
                    AS competitive_decision,

                ct.decision_reason
                    AS competitive_reason,

                ct.white_sr_change,

                ct.black_sr_change,

                ct.white_sr_before,
                ct.white_sr_after,
                ct.black_sr_before,
                ct.black_sr_after

            FROM games g

            LEFT JOIN users white
                ON white.id =
                    g.white_user_id

            LEFT JOIN users black
                ON black.id =
                    g.black_user_id

            LEFT JOIN (
                SELECT game_id, COUNT(*) AS move_count, MAX(created_at) AS last_move_at
                FROM game_moves
                GROUP BY game_id
            ) gm
                ON gm.game_id = g.id

            LEFT JOIN competitive_transactions ct
                ON ct.game_id =
                    g.id

            WHERE
                g.white_user_id = ?
                OR
                g.black_user_id = ?

            ORDER BY
                g.updated_at DESC,
                g.id DESC

            LIMIT ? OFFSET ?
            """,
            (
                user["id"],
                user["id"],
                safe_limit + 1,
                safe_offset,
            ),
        )

        rows = await cursor.fetchall()

        has_more = len(rows) > safe_limit
        rows = rows[:safe_limit]
        games = []

        for row in rows:
            color = get_user_color(
                row,
                user["id"],
            )

            if color == "white":
                rating_before = (
                    row[
                        "white_rating_before"
                    ]
                )

                rating_after = (
                    row[
                        "white_rating_after"
                    ]
                )

                rating_change = (
                    row[
                        "white_rating_change"
                    ]
                )

                sr_change = (
                    row[
                        "white_sr_change"
                    ]
                )

            else:
                rating_before = (
                    row[
                        "black_rating_before"
                    ]
                )

                rating_after = (
                    row[
                        "black_rating_after"
                    ]
                )

                rating_change = (
                    row[
                        "black_rating_change"
                    ]
                )

                sr_change = (
                    row[
                        "black_sr_change"
                    ]
                )

            white = None

            if (
                row[
                    "white_discord_id"
                ]
                is not None
            ):
                white = {
                    "username":
                        row[
                            "white_username"
                        ],

                    "display_name":
                        row[
                            "white_display_name"
                        ],

                    "avatar_url":
                        row[
                            "white_avatar_url"
                        ],
                }

            black = None

            if (
                row[
                    "black_discord_id"
                ]
                is not None
            ):
                black = {
                    "username":
                        row[
                            "black_username"
                        ],

                    "display_name":
                        row[
                            "black_display_name"
                        ],

                    "avatar_url":
                        row[
                            "black_avatar_url"
                        ],
                }

            games.append(
                {
                    "game_id":
                        row[
                            "public_id"
                        ],

                    "mode":
                        row["mode"],

                    "rating_pool":
                        row[
                            "rating_pool"
                        ],

                    "status":
                        row[
                            "status"
                        ],

                    "result":
                        row[
                            "result"
                        ],

                    "termination_reason":
                        row[
                            "termination_reason"
                        ],

                    "competitive_decision":
                        row[
                            "competitive_decision"
                        ],

                    "user_color":
                        color,

                    "user_result":
                        get_user_result(
                            row,
                            user["id"],
                        ),

                    "rating_before":
                        display_number(
                            rating_before
                        ),

                    "rating_after":
                        display_number(
                            rating_after
                        ),

                    "rating_change":
                        display_number(
                            rating_change
                        ),

                    "sr_change":
                        sr_change,

                    "sr_before": row["white_sr_before"] if color == "white" else row["black_sr_before"],
                    "sr_after": row["white_sr_after"] if color == "white" else row["black_sr_after"],

                    "white":
                        white,

                    "black":
                        black,

                    "move_count":
                        int(
                            row[
                                "move_count"
                            ]
                            or 0
                        ),

                    "created_at":
                        row[
                            "created_at"
                        ],

                    "started_at":
                        row[
                            "started_at"
                        ],

                    "updated_at":
                        row[
                            "updated_at"
                        ],

                    "completed_at":
                        row[
                            "completed_at"
                        ],

                    "last_move_at":
                        row[
                            "last_move_at"
                        ],
                }
            )

        return {
            "ok": True,
            "games": games,
            "has_more": has_more,
            "limit": safe_limit,
            "offset": safe_offset,
        }

    finally:
        await db.close()


async def make_move(
    public_id,
    discord_id,
    uci_move,
):
    db = await connect()

    try:
        user = (
            await get_user_by_discord_id(
                db,
                discord_id,
            )
        )

        if user is None:
            return {
                "ok": False,
                "error":
                    "user_not_found",
            }

        cursor = await db.execute(
            """
            SELECT *
            FROM games
            WHERE public_id = ?
            """,
            (
                public_id,
            ),
        )

        game = await cursor.fetchone()

        if game is None:
            return {
                "ok": False,
                "error":
                    "game_not_found",
            }

        if (
            game["status"]
            ==
            "waiting"
        ):
            return {
                "ok": False,
                "error":
                    "waiting_for_opponent",
            }

        if (
            game["status"]
            != "active"
        ):
            return {
                "ok": False,
                "error":
                    "game_not_active",
            }

        if (
            user["id"]
            ==
            game[
                "white_user_id"
            ]
        ):
            player_color = "white"

        elif (
            user["id"]
            ==
            game[
                "black_user_id"
            ]
        ):
            player_color = "black"

        else:
            return {
                "ok": False,
                "error":
                    "not_a_player",
            }

        # Repetition adjudication needs history; FEN alone loses repetition counts.
        board = chess.Board(game["starting_fen"])
        for stored in await get_move_history(db, game["id"]):
            board.push_uci(stored["uci"])
        if board.fen() != game["current_fen"]:
            raise ValueError("Stored game history does not match current position")

        expected_color = (
            "white"
            if board.turn
            else "black"
        )

        if (
            player_color
            != expected_color
        ):
            return {
                "ok": False,
                "error":
                    "not_your_turn",
            }

        try:
            move = (
                chess.Move.from_uci(
                    uci_move
                )
            )

        except ValueError:
            return {
                "ok": False,
                "error":
                    "invalid_uci",
            }

        if (
            move
            not in
            board.legal_moves
        ):
            return {
                "ok": False,
                "error":
                    "illegal_move",
            }

        san = board.san(
            move
        )

        board.push(
            move
        )

        fen_after = board.fen()

        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS count
            FROM game_moves
            WHERE game_id = ?
            """,
            (
                game["id"],
            ),
        )

        count_row = (
            await cursor.fetchone()
        )

        ply = (
            int(
                count_row[
                    "count"
                ]
                or 0
            )
            +
            1
        )

        move_number = (
            ply + 1
        ) // 2

        try:
            await db.execute(
                """
                INSERT INTO game_moves (
                    game_id,
                    move_number,
                    ply,
                    user_id,
                    color,
                    uci,
                    san,
                    fen_after
                )

                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game["id"],
                    move_number,
                    ply,
                    user["id"],
                    player_color,
                    uci_move,
                    san,
                    fen_after,
                ),
            )

        except aiosqlite.IntegrityError:
            await db.rollback()

            return {
                "ok": False,
                "error":
                    "move_conflict",
            }

        if board.is_checkmate():
            status = (
                "black_win"
                if board.turn
                else "white_win"
            )

            result = (
                "0-1"
                if board.turn
                else "1-0"
            )

            updated = (
                await finalize_game(
                    db,

                    game["id"],

                    status,
                    result,

                    "checkmate",

                    fen_after,
                )
            )

        elif board.is_stalemate():
            updated = (
                await finalize_game(
                    db,

                    game["id"],

                    "draw",
                    "1/2-1/2",

                    "stalemate",

                    fen_after,
                )
            )

        elif (
            board.is_insufficient_material()
        ):
            updated = (
                await finalize_game(
                    db,

                    game["id"],

                    "draw",
                    "1/2-1/2",

                    "insufficient_material",

                    fen_after,
                )
            )

        elif (
            board.is_seventyfive_moves()
        ):
            updated = (
                await finalize_game(
                    db,

                    game["id"],

                    "draw",
                    "1/2-1/2",

                    "seventyfive_move_rule",

                    fen_after,
                )
            )

        elif (
            board.is_fivefold_repetition()
        ):
            updated = (
                await finalize_game(
                    db,

                    game["id"],

                    "draw",
                    "1/2-1/2",

                    "fivefold_repetition",

                    fen_after,
                )
            )

        else:
            await db.execute(
                """
                UPDATE games

                SET
                    current_fen = ?,

                    updated_at =
                        CURRENT_TIMESTAMP

                WHERE
                    id = ?
                    AND
                    status =
                        'active'
                """,
                (
                    fen_after,
                    game["id"],
                ),
            )

            await db.commit()

            cursor = await db.execute(
                """
                SELECT *
                FROM games
                WHERE id = ?
                """,
                (
                    game["id"],
                ),
            )

            updated = (
                await cursor.fetchone()
            )

        return {
            "ok": True,

            "move": {
                "move_number":
                    move_number,

                "ply":
                    ply,

                "color":
                    player_color,

                "uci":
                    uci_move,

                "san":
                    san,

                "fen_after":
                    fen_after,
            },

            "game":
                await build_game_payload(
                    db,
                    updated,
                ),
        }

    finally:
        await db.close()
