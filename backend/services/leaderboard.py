"""Public, settlement-backed Bishoply rankings."""
from backend.database.db import connect, DEFAULT_RATING_POOL


async def read(kind="rating", limit=50, offset=0, current_user=None):
    kind = "sr" if kind == "sr" else "rating"
    limit = max(1, min(int(limit), 100))
    offset = max(0, min(int(offset), 100000))
    value = "p.sr" if kind == "sr" else "r.rating"
    public_field = "sr" if kind == "sr" else "chess_rating"
    tie = "r.rated_games DESC, u.updated_at ASC, u.id ASC" if kind == "rating" else "p.total_sr_earned DESC, u.updated_at ASC, u.id ASC"
    db = await connect()
    try:
        rows = await (await db.execute(f"""SELECT u.display_name,u.username,u.avatar_url,
                CAST({value} AS INTEGER) AS score, r.rated_games,r.wins,r.losses,r.draws
                FROM users u JOIN skill_ratings r ON r.user_id=u.id AND r.pool=?
                JOIN progression p ON p.user_id=u.id
                WHERE r.rating IS NOT NULL AND p.sr IS NOT NULL
                ORDER BY {value} DESC, {tie} LIMIT ? OFFSET ?""", (DEFAULT_RATING_POOL, limit + 1, offset))).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        leaderboard = [{"rank": offset + i + 1, "display_name": row["display_name"] or row["username"],
                        "avatar_url": row["avatar_url"], public_field: int(row["score"]),
                        **({"games_played": int(row["rated_games"] or 0), "wins": int(row["wins"] or 0),
                            "losses": int(row["losses"] or 0), "draws": int(row["draws"] or 0)} if kind == "rating" else {})}
                       for i, row in enumerate(rows)]
        yours = None
        if current_user is not None:
            row = await (await db.execute(f"""SELECT r.rating,p.sr FROM users u
                    JOIN skill_ratings r ON r.user_id=u.id AND r.pool=? JOIN progression p ON p.user_id=u.id
                    WHERE u.id=?""", (DEFAULT_RATING_POOL, int(current_user)))).fetchone()
            if row:
                score = row["sr"] if kind == "sr" else row["rating"]
                higher = await (await db.execute(f"""SELECT COUNT(*) AS n FROM users u
                    JOIN skill_ratings r ON r.user_id=u.id AND r.pool=? JOIN progression p ON p.user_id=u.id
                    WHERE {value} > ?""", (DEFAULT_RATING_POOL, score))).fetchone()
                yours = {"rank": int(higher["n"]) + 1, public_field: int(round(float(score)))}
        return {"kind": kind, "entries": leaderboard, "limit": limit, "offset": offset, "has_more": has_more, "your_rank": yours}
    finally:
        await db.close()
