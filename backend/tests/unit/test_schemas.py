"""Unit tests for request validation schemas (no database required)."""

import math

import pytest
from pydantic import ValidationError

from app.schemas.auth import RegisterRequest
from app.schemas.rating import RatingUpsert


class TestRatingValidation:
    @pytest.mark.parametrize("value", [0.5, 1, 2.5, 3.0, 4.5, 5, 5.0])
    def test_valid_half_star_ratings_are_accepted(self, value):
        assert RatingUpsert(rating=value).rating == value

    @pytest.mark.parametrize(
        "value",
        [
            0,  # below minimum
            0.0,
            0.25,  # not a half-star step
            -1,
            5.5,  # above maximum
            10,
            3.3,
            4.75,
            math.nan,
            math.inf,
        ],
    )
    def test_out_of_range_or_off_step_ratings_are_rejected(self, value):
        with pytest.raises(ValidationError):
            RatingUpsert(rating=value)

    @pytest.mark.parametrize("value", ["4.5", "four", True, None, [4]])
    def test_non_numeric_ratings_are_rejected(self, value):
        with pytest.raises(ValidationError):
            RatingUpsert(rating=value)

    def test_unexpected_fields_are_rejected(self):
        with pytest.raises(ValidationError):
            RatingUpsert(rating=4.0, user_id=999)


class TestRegisterValidation:
    def test_email_is_normalised_to_lower_case(self):
        request = RegisterRequest(email="Alice.Smith@Example.COM", password="long-enough-password")
        assert request.email == "alice.smith@example.com"

    @pytest.mark.parametrize("email", ["not-an-email", "a@", "@example.com", "", "a b@example.com"])
    def test_invalid_emails_are_rejected(self, email):
        with pytest.raises(ValidationError):
            RegisterRequest(email=email, password="long-enough-password")

    @pytest.mark.parametrize("password", ["", "short", "x" * 14, "x" * 129])
    def test_passwords_outside_length_limits_are_rejected(self, password):
        with pytest.raises(ValidationError):
            RegisterRequest(email="a@example.com", password=password)

    @pytest.mark.parametrize("password", ["x" * 15, "x" * 128])
    def test_passwords_at_length_boundaries_are_accepted(self, password):
        assert RegisterRequest(email="a@example.com", password=password).password == password
