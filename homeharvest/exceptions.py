class InvalidListingType(Exception):
    """Raised when a provided listing type is does not exist."""


class NoResultsFound(Exception):
    """Raised when no results are found for the given location"""


class GeoCoordsNotFound(Exception):
    """Raised when no property is found for the given address"""


class InvalidDate(Exception):
    """Raised when only one of date_from or date_to is provided or not in the correct format. ex: 2023-10-23"""


class AuthenticationError(Exception):
    """Raised when there is an issue with the authentication process."""
    def __init__(self, *args, response):
        super().__init__(*args)

        self.response = response
