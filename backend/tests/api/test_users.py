"""API tests for the account endpoints added in the intermediate backend phase:
profile update, email change, password change and rating statistics, and
the profile picture added in Phase 7.5.

Authentication itself (missing/invalid/expired tokens) is covered once for
every protected endpoint in test_auth.py and is not repeated here.
"""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.helpers import TEST_NAME, TEST_PASSWORD, login

pytestmark = pytest.mark.db

ME_URL = "/api/v1/users/me"
NEW_PASSWORD = "Another-Long-Passphrase-7"


def test_profile_update_changes_only_the_fields_sent(client: TestClient, alice_headers):
    response = client.patch(
        ME_URL,
        headers=alice_headers,
        json={"location": "  Dublin, Ireland ", "bio": "Film noir fan.\nAlso loves westerns."},
    )
    assert response.status_code == 200
    body = response.json()
    # Trimmed; the bio keeps its line break; the name was not sent, so it is unchanged.
    assert (body["name"], body["location"], body["bio"]) == (
        TEST_NAME,
        "Dublin, Ireland",
        "Film noir fan.\nAlso loves westerns.",
    )

    # An empty string (or null) removes location/bio; the name can be changed.
    response = client.patch(ME_URL, headers=alice_headers, json={"name": "Alice", "bio": ""})
    assert response.status_code == 200
    stored = client.get(ME_URL, headers=alice_headers).json()
    assert (stored["name"], stored["location"], stored["bio"]) == ("Alice", "Dublin, Ireland", None)


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},  # The name is required: it can be changed, not removed.
        {"name": "   "},
        {"name": "x" * 101},
        {"location": "x" * 101},
        {"bio": "x" * 501},
        {"location": "Dub\x00lin"},  # Control characters are rejected.
        {"name": "Al\nice"},  # Line breaks only in the bio.
        {"email": "new@example.com"},  # Email has its own endpoint (password needed).
    ],
)
def test_invalid_profile_updates_are_rejected(client: TestClient, alice_headers, payload):
    assert client.patch(ME_URL, headers=alice_headers, json=payload).status_code == 422


def test_email_change_needs_the_current_password_and_a_free_email(
    client: TestClient, alice_headers, bob_headers
):
    url = f"{ME_URL}/email"
    wrong = client.put(
        url, headers=alice_headers, json={"new_email": "a2@example.com", "current_password": "no"}
    )
    assert (wrong.status_code, wrong.json()) == (403, {"detail": "Current password is incorrect"})

    taken = client.put(
        url,
        headers=alice_headers,
        json={"new_email": "BOB@example.com", "current_password": TEST_PASSWORD},
    )
    assert (taken.status_code, taken.json()) == (409, {"detail": "Email already registered"})

    changed = client.put(
        url,
        headers=alice_headers,
        json={"new_email": "Alice.New@Example.com", "current_password": TEST_PASSWORD},
    )
    assert changed.status_code == 200
    assert changed.json()["email"] == "alice.new@example.com"  # Normalised as at registration.
    # The login email changed; the existing token still works (it identifies the user by ID).
    assert login(client, "alice.new@example.com").status_code == 200
    assert login(client, "alice@example.com").status_code == 401
    assert client.get(ME_URL, headers=alice_headers).status_code == 200


def test_password_change_needs_the_current_password(client: TestClient, alice_headers):
    url = f"{ME_URL}/password"
    wrong = client.put(
        url, headers=alice_headers, json={"current_password": "wrong", "new_password": NEW_PASSWORD}
    )
    assert wrong.status_code == 403

    too_short = client.put(
        url,
        headers=alice_headers,
        json={"current_password": TEST_PASSWORD, "new_password": "tiny-pw9"},
    )
    assert too_short.status_code == 422
    assert "tiny-pw9" not in too_short.text  # Rejected values are never echoed.

    changed = client.put(
        url,
        headers=alice_headers,
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert (changed.status_code, changed.content) == (204, b"")
    assert login(client, "alice@example.com").status_code == 401
    assert login(client, "alice@example.com", NEW_PASSWORD).status_code == 200


def _png_with_gps_metadata() -> bytes:
    """A small transparent PNG carrying EXIF metadata (a GPS entry)."""
    image = Image.new("RGBA", (300, 200), (255, 0, 0, 0))
    exif = Image.Exif()
    exif[0x8825] = {2: (53.0, 20.0, 0.0)}  # GPSInfo: latitude
    output = BytesIO()
    image.save(output, format="PNG", exif=exif)
    return output.getvalue()


def test_profile_picture_is_reencoded_owner_only_and_removable(
    client: TestClient, alice_headers, bob_headers
):
    url = f"{ME_URL}/picture"
    assert client.get(url, headers=alice_headers).status_code == 404
    assert client.get(ME_URL, headers=alice_headers).json()["picture_updated_at"] is None

    uploaded = client.put(
        url,
        headers=alice_headers,
        files={"picture": ("me.png", _png_with_gps_metadata(), "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["picture_updated_at"] is not None

    # The stored picture is a new 512x512 JPEG without the original metadata.
    stored = client.get(url, headers=alice_headers)
    assert stored.status_code == 200
    assert stored.headers["content-type"] == "image/jpeg"
    assert stored.headers["x-content-type-options"] == "nosniff"
    with Image.open(BytesIO(stored.content)) as image:
        assert (image.format, image.size) == ("JPEG", (512, 512))
        assert len(image.getexif()) == 0

    # Owner-only: another user sees only their own (missing) picture.
    assert client.get(url, headers=bob_headers).status_code == 404

    # A file that is not an image (here an SVG, which may contain scripts) and
    # a file over 2 MB are rejected; the stored picture is unchanged.
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    not_image = client.put(
        url, headers=alice_headers, files={"picture": ("x.svg", svg, "image/svg+xml")}
    )
    assert not_image.status_code == 422
    too_large = client.put(
        url,
        headers=alice_headers,
        files={"picture": ("big.jpg", b"\xff" * (2 * 1024 * 1024 + 1), "image/jpeg")},
    )
    assert too_large.status_code == 413
    assert client.get(url, headers=alice_headers).content == stored.content

    assert client.delete(url, headers=alice_headers).status_code == 204
    assert client.get(url, headers=alice_headers).status_code == 404
    assert client.get(ME_URL, headers=alice_headers).json()["picture_updated_at"] is None


def test_rating_statistics_per_genre(client: TestClient, alice_headers, bob_headers):
    # Toy Story and Toy Story 2: Adventure|Animation|Children|Comedy|Fantasy;
    # Shawshank: Crime|Drama; Dune: Drama|Fantasy|Sci-Fi.
    for movie_id, value in {1: 5.0, 3114: 4.0, 318: 2.0, 7842: 3.0}.items():
        client.put(f"/api/v1/ratings/{movie_id}", headers=alice_headers, json={"rating": value})

    stats = client.get(f"{ME_URL}/stats", headers=alice_headers).json()
    assert (stats["rating_count"], stats["average_rating"]) == (4, 3.5)
    # A movie counts once in each of its genres. Most rated first, then higher
    # average, then name.
    assert [(g["genre"], g["rating_count"], g["average_rating"]) for g in stats["genres"]] == [
        ("Fantasy", 3, 4.0),
        ("Adventure", 2, 4.5),
        ("Animation", 2, 4.5),
        ("Children", 2, 4.5),
        ("Comedy", 2, 4.5),
        ("Drama", 2, 2.5),
        ("Sci-Fi", 1, 3.0),
        ("Crime", 1, 2.0),
    ]

    # Only the caller's ratings are used: Bob has none.
    empty = client.get(f"{ME_URL}/stats", headers=bob_headers).json()
    assert empty == {"rating_count": 0, "average_rating": None, "genres": []}
