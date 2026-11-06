"""Helper functions shared by the API tests."""

# Fixed, test-only values. They are not secrets and are never used outside tests.
TEST_JWT_SECRET = "test-only-jwt-secret-key-never-used-in-real-environments"
TEST_PASSWORD = "CorrectHorse-42"

# A small extract of the real catalogue (ml/data/processed/movies_catalogue.csv),
# copied exactly, as (movie_id, title, genres, tmdb_id, imdb_id). It is loaded
# before every database test because ratings and watchlist entries must now
# reference a catalogue movie. It includes the IDs used by the older tests and
# Dune (2000), the only catalogue movie without a TMDB ID. Movies 29, 293 and
# 2542 were added for the normalized search (accents, trailing articles,
# alternative titles in parentheses, "&" and commas).
TEST_MOVIES = [
    (1, "Toy Story (1995)", "Adventure|Animation|Children|Comedy|Fantasy", 862, 114709),
    (2, "Jumanji (1995)", "Adventure|Children|Fantasy", 8844, 113497),
    (3, "Grumpier Old Men (1995)", "Comedy|Romance", 15602, 113228),
    (5, "Father of the Bride Part II (1995)", "Comedy", 11862, 113041),
    (6, "Heat (1995)", "Action|Crime|Thriller", 949, 113277),
    (7, "Sabrina (1995)", "Comedy|Romance", 11860, 114319),
    (10, "GoldenEye (1995)", "Action|Adventure|Thriller", 710, 113189),
    (20, "Money Train (1995)", "Action|Comedy|Crime|Drama|Thriller", 11517, 113845),
    (
        29,
        "City of Lost Children, The (Cité des enfants perdus, La) (1995)",
        "Adventure|Drama|Fantasy|Mystery|Sci-Fi",
        902,
        112682,
    ),
    (30, "Shanghai Triad (Yao a yao yao dao waipo qiao) (1995)", "Crime|Drama", 37557, 115012),
    (
        293,
        "Léon: The Professional (a.k.a. The Professional) (Léon) (1994)",
        "Action|Crime|Drama|Thriller",
        101,
        110413,
    ),
    (318, "Shawshank Redemption, The (1994)", "Crime|Drama", 278, 111161),
    (2542, "Lock, Stock & Two Smoking Barrels (1998)", "Comedy|Crime|Thriller", 100, 120735),
    (2571, "Matrix, The (1999)", "Action|Sci-Fi|Thriller", 603, 133093),
    (3114, "Toy Story 2 (1999)", "Adventure|Animation|Children|Comedy|Fantasy", 863, 120363),
    (7842, "Dune (2000)", "Drama|Fantasy|Sci-Fi", None, 142032),
    (
        78499,
        "Toy Story 3 (2010)",
        "Adventure|Animation|Children|Comedy|Fantasy|IMAX",
        10193,
        435761,
    ),
]

# A valid movie ID that is not in TEST_MOVIES (nor in the real catalogue).
UNKNOWN_MOVIE_ID = 999_999


def register_user(client, email: str, password: str = TEST_PASSWORD):
    return client.post("/api/v1/auth/register", json={"email": email, "password": password})


def login(client, email: str, password: str = TEST_PASSWORD):
    # OAuth2 password flow: form-encoded body with "username" and "password".
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


def auth_headers(client, email: str, password: str = TEST_PASSWORD) -> dict[str, str]:
    """Register a user, log in, and return the Authorization header."""
    assert register_user(client, email, password).status_code == 201
    response = login(client, email, password)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
