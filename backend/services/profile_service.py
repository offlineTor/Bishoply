from backend.database.db import (
    DEFAULT_RATING_POOL,
    connect,
    ensure_competitive_profile,
)


FOUNDER_USERNAME = "sippinturps"


def public_int(value):
    if value is None:
        return 0

    return int(
        round(
            float(value)
        )
    )


def confidence_label(rd):
    rd = float(rd)

    if rd >= 250:
        return "Low"

    if rd >= 150:
        return "Developing"

    if rd >= 80:
        return "Good"

    return "High"


async def get_profile_by_discord_id(
    discord_id: int,
):
    db = await connect()

    try:
        cursor = await db.execute(
            """
            SELECT
                id,
                discord_id,
                username,
                display_name,
                avatar_url,
                level,
                xp
                ,created_at
            FROM users
            WHERE discord_id = ?
            """,
            (
                int(discord_id),
            ),
        )

        user = await cursor.fetchone()

        if user is None:
            return None

        await ensure_competitive_profile(
            db,
            user["id"],
        )

        cursor = await db.execute(
            """
            SELECT
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
                user["id"],
                DEFAULT_RATING_POOL,
            ),
        )

        rating = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT
                sr,
                peak_sr,
                total_sr_earned,
                games_rewarded
            FROM progression
            WHERE user_id = ?
            """,
            (
                user["id"],
            ),
        )

        progression = await cursor.fetchone()

        wins = int(
            rating["wins"]
            or 0
        )

        losses = int(
            rating["losses"]
            or 0
        )

        draws = int(
            rating["draws"]
            or 0
        )

        rated_games = int(
            rating["rated_games"]
            or 0
        )

        total_games = (
            wins
            +
            losses
            +
            draws
        )

        win_rate = (
            round(
                wins
                /
                total_games
                *
                100,
                1,
            )
            if total_games
            else 0.0
        )

        rd = float(
            rating[
                "rating_deviation"
            ]
        )

        title = (
            "Founder & CEO"
            if user["username"] == FOUNDER_USERNAME
            else None
        )

        return {
            "discord_id":
                str(
                    user["discord_id"]
                ),

            "username":
                user["username"],

            "display_name":
                user["display_name"],

            "avatar_url":
                user["avatar_url"],

            "title":
                title,

            "level":
                int(
                    user["level"]
                    or 1
                ),

            "xp":
                int(
                    user["xp"]
                    or 0
                ),

            "account_created_at": user["created_at"],

            "sr":
                int(
                    progression["sr"]
                ),

            "peak_sr":
                int(
                    progression[
                        "peak_sr"
                    ]
                ),

            "total_sr_earned":
                int(
                    progression[
                        "total_sr_earned"
                    ]
                    or 0
                ),

            "games_rewarded":
                int(
                    progression[
                        "games_rewarded"
                    ]
                    or 0
                ),

            "rating":
                public_int(
                    rating["rating"]
                ),

            "peak_rating":
                public_int(
                    rating[
                        "peak_rating"
                    ]
                ),

            "rating_deviation":
                public_int(
                    rd
                ),

            "rating_confidence":
                confidence_label(
                    rd
                ),

            "provisional":
                bool(
                    rating[
                        "provisional"
                    ]
                ),

            "rated_games":
                rated_games,

            "placement_games_remaining":
                max(
                    0,
                    20 - rated_games,
                ),

            "wins":
                wins,

            "losses":
                losses,

            "draws":
                draws,

            "games_played":
                rated_games,

            "win_rate":
                win_rate,

            "current_win_streak":
                int(
                    rating[
                        "current_win_streak"
                    ]
                    or 0
                ),

            "best_win_streak":
                int(
                    rating[
                        "best_win_streak"
                    ]
                    or 0
                ),

            "rating_model":
                rating[
                    "model_version"
                ],

            "rating_pool":
                DEFAULT_RATING_POOL,

            "last_rated_at":
                rating[
                    "last_rated_at"
                ],
        }

    finally:
        await db.close()
