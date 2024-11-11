"""
homeharvest.zillow.__init__
~~~~~~~~~~~~

This module implements the scraper for zillow.com
"""
import datetime
import re
import json

from .. import Scraper
from requests.exceptions import HTTPError
from ....exceptions import GeoCoordsNotFound, NoResultsFound
from ..models import Property, Address, ListingType, Description
import urllib.parse


class ZillowScraper(Scraper):
    def __init__(self, scraper_input):
        super().__init__(scraper_input)

        self.session.headers.update({
            'authority': 'www.zillow.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'max-age=0',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
        })

        if not self.is_plausible_location(self.location):
            raise NoResultsFound("Invalid location input: {}".format(self.location))

        listing_type_to_url_path = {
            ListingType.FOR_SALE: "for_sale",
            ListingType.FOR_RENT: "for_rent",
            ListingType.SOLD: "recently_sold",
        }

        self.url = f"https://www.zillow.com/homes/{listing_type_to_url_path[self.listing_type]}/{self.location}_rb/"

    def is_plausible_location(self, location: str) -> bool:
        url = (
            "https://www.zillowstatic.com/autocomplete/v3/suggestions?q={"
            "}&abKey=6666272a-4b99-474c-b857-110ec438732b&clientId=homepage-render"
        ).format(urllib.parse.quote(location))

        resp = self.session.get(url)

        return resp.json()["results"] != []

    def search(self):
        resp = self.session.get(self.url)
        if resp.status_code != 200:
            raise HTTPError(
                f"bad response status code: {resp.status_code}"
            )
        content = resp.text

        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            content,
            re.DOTALL,
        )
        if not match:
            raise NoResultsFound("No results were found for Zillow with the given Location.")

        json_str = match.group(1)
        data = json.loads(json_str)

        if "searchPageState" in data["props"]["pageProps"]:
            pattern = r'window\.mapBounds = \{\s*"west":\s*(-?\d+\.\d+),\s*"east":\s*(-?\d+\.\d+),\s*"south":\s*(-?\d+\.\d+),\s*"north":\s*(-?\d+\.\d+)\s*\};'

            match = re.search(pattern, content)

            if match:
                coords = [float(coord) for coord in match.groups()]
                return self._fetch_properties_backend(coords)

            else:
                raise GeoCoordsNotFound("Box bounds could not be located.")

        elif "gdpClientCache" in data["props"]["pageProps"]:
            gdp_client_cache = json.loads(data["props"]["pageProps"]["gdpClientCache"])
            main_key = list(gdp_client_cache.keys())[0]

            property_data = gdp_client_cache[main_key]["property"]
            property = self._get_single_property_page(property_data)

            return [property]
        raise NoResultsFound("Specific property data not found in the response.")

    def _fetch_properties_backend(self, coords):
        url = "https://www.zillow.com/async-create-search-page-state"

        filter_state_for_sale = {
            "sortSelection": {
                # "value": "globalrelevanceex"
                "value": "days"
            },
            "isAllHomes": {"value": True},
        }

        filter_state_for_rent = {
            "isForRent": {"value": True},
            "isForSaleByAgent": {"value": False},
            "isForSaleByOwner": {"value": False},
            "isNewConstruction": {"value": False},
            "isComingSoon": {"value": False},
            "isAuction": {"value": False},
            "isForSaleForeclosure": {"value": False},
            "isAllHomes": {"value": True},
        }

        filter_state_sold = {
            "isRecentlySold": {"value": True},
            "isForSaleByAgent": {"value": False},
            "isForSaleByOwner": {"value": False},
            "isNewConstruction": {"value": False},
            "isComingSoon": {"value": False},
            "isAuction": {"value": False},
            "isForSaleForeclosure": {"value": False},
            "isAllHomes": {"value": True},
        }

        selected_filter = (
            filter_state_for_rent
            if self.listing_type == ListingType.FOR_RENT
            else filter_state_for_sale
            if self.listing_type == ListingType.FOR_SALE
            else filter_state_sold
        )

        payload = {
            "searchQueryState": {
                "pagination": {},
                "isMapVisible": True,
                "mapBounds": {
                    "west": coords[0],
                    "east": coords[1],
                    "south": coords[2],
                    "north": coords[3],
                },
                "filterState": selected_filter,
                "isListVisible": True,
                "mapZoom": 11,
            },
            "wants": {"cat1": ["mapResults"]},
            "isDebugRequest": False,
        }
        resp = self.session.put(url, json=payload)
        if resp.status_code != 200:
            raise HTTPError(
                f"bad response status code: {resp.status_code}"
            )
        return self._parse_properties(resp.json())


    def _parse_properties(self, property_data: dict):
        mapresults = property_data["cat1"]["searchResults"]["mapResults"]

        properties_list = []

        for result in mapresults:
            if "hdpData" in result:
                home_info = result["hdpData"]["homeInfo"]
                property_obj = Property(
                    site_name=self.site_name,
                    mls=None,
                    mls_id=result.get("info1String").split("MLS ID #")[1] if "info1String" in result and "MLS ID #" in result["info1String"] else None,
                    property_url=f"https://www.zillow.com{result['detailUrl']}",
                    property_id=home_info["zpid"],
                    listing_id=home_info["zpid"],
                    status=home_info.get("homeStatus"),
                    list_price=re.sub(r'[^0-9\-.]', '', result.get("price")),
                    list_price_min=re.sub(r'[^0-9\-.]', '', result.get("price")),
                    list_price_max=re.sub(r'[^0-9\-.]', '', result.get("price")),
                    list_date=_parse_list_date(home_info["timeOnZillow"]),
                    prc_sqft=int(home_info["price"] // home_info["livingArea"]) if "livingArea" in home_info and int(home_info["livingArea"]) != 0 and "price" in home_info else None,
                    last_sold_date=None,
                    new_construction=None,
                    hoa_fee=None,
                    address=_parse_address(result),
                    latitude=result["latLong"]["latitude"],
                    longitude=result["latLong"]["longitude"],
                    description=Description(
                        primary_photo=result["imgSrc"],
                        alt_photos=None,
                        style=home_info["homeType"],
                        beds=int(home_info["bedrooms"]) if "bedrooms" in home_info else None,
                        baths_full=int(home_info["bathrooms"]) if "bathrooms" in home_info else None,
                        baths_half=1 if ("bathrooms" in home_info and float(home_info["bathrooms"]) % 1 == 0.5) else 0,
                        sqft=int(home_info["livingArea"]) if "livingArea" in home_info else None,
                        lot_sqft=_parse_lot_sqft(result),
                        sold_price=None,
                        year_built=None,
                        garage=None,
                        stories=None
                    ),
                    neighborhoods=None,
                    county=None,
                    fips_code=None,
                    days_on_mls=self.calculate_days_on_zillow(home_info["timeOnZillow"]),
                    nearby_schools=None,
                    assessed_value=None,
                    estimated_value=self.calculate_estimated_value(home_info),
                    advertisers=None
                )
            elif "isBuilding" in result:
                property_obj = Property(
                    site_name=self.site_name,
                    mls=None,
                    mls_id=result.get("info1String").split("MLS ID #")[1] if "info1String" in result and "MLS ID #" in result["info1String"] else None,
                    property_url=f"https://www.zillow.com{result['detailUrl']}",
                    property_id=result["plid"],
                    listing_id=result["plid"],
                    status=result["statusType"],
                    list_price=re.sub(r'[^0-9\-.]', '', result.get("price")),
                    list_price_min=re.sub(r'[^0-9\-.]', '', result.get("price")),
                    list_price_max=re.sub(r'[^0-9\-.]', '', result.get("price")),
                    list_date=_parse_list_date(result["timeOnZillow"]),
                    prc_sqft=int(re.sub(r'[^0-9\-.]', '', result.get("price"))) // result["minArea"] if "minArea" in result and int(result["minArea"]) != 0 and "price" in result else None,
                    last_sold_date=None,
                    new_construction=None,
                    hoa_fee=None,
                    address=_parse_address(result),
                    latitude=result["latLong"]["latitude"],
                    longitude=result["latLong"]["longitude"],
                    description=Description(
                        primary_photo=result["imgSrc"],
                        alt_photos=None,
                        style="APARTMENT",
                        beds=int(result["minBeds"]) if "minBeds" in result else None,
                        baths_full=int(result["minBaths"] )if "minBaths" in result else None,
                        baths_half=1 if ("minBaths" in result and float(result["minBaths"]) % 1 == 0.5) else 0,
                        sqft=int(result["minArea"]) if "minArea" in result else None,
                        lot_sqft=_parse_lot_sqft(result),
                        sold_price=None,
                        year_built=None,
                        garage=None,
                        stories=None
                    ),
                    neighborhoods=None,
                    county=None,
                    fips_code=None,
                    days_on_mls=self.calculate_days_on_zillow(result["timeOnZillow"]),
                    nearby_schools=None,
                    assessed_value=None,
                    estimated_value=None,
                    advertisers=None
                )

            properties_list.append(property_obj)

        return properties_list

    def _get_single_property_page(self, property_data: dict):
        """
        This method is used when a user enters the exact location & zillow returns just one property
        """
        url = (
            f"https://www.zillow.com{property_data['hdpUrl']}"
            if "zillow.com" not in property_data["hdpUrl"]
            else property_data["hdpUrl"]
        )
        address_data = property_data["address"]
        return Property(
            site_name=self.site_name,
            property_url=url,
            address=Address(
                # TODO: address
                # address_one, address_two = parse_address_one(address_data["streetAddress"])
                # address_one=address_one,
                # address_two=address_two if address_two else "#",
                city=address_data["city"],
                state=address_data["state"],
                zip_code=address_data["zipcode"],
            ),
            stories=property_data.get("resoFacts", {}).get("stories"),
            mls_id=property_data.get("attributionInfo", {}).get("mlsId"),
            latitude=property_data.get("latitude"),
            longitude=property_data.get("longitude")
        )

    def calculate_days_on_zillow(self, timeOnZillow: int) -> int:
        return int(timeOnZillow / 86400000)

    def calculate_estimated_value(self, home_info) -> int:
        if home_info["homeStatus"] == "FOR_RENT":
            return home_info["zestimate"] if "zestimate" in home_info else None
        else:
            return home_info["rentZestimate"] if "rentZestimate" in home_info else None

@staticmethod
def _parse_address(result: dict):
    street: str = None
    unit: str = None
    city: str = None
    state: str = None
    zip: str = None

    if "hdpData" in result and "homeInfo" in result["hdpData"]:
        street = result["hdpData"]["homeInfo"].get("streetAddress")
        city=result["hdpData"]["homeInfo"].get("city")
        state=result["hdpData"]["homeInfo"].get("state")
        zip=result["hdpData"]["homeInfo"].get("zipcode")
    else:
        fullAddr: str = result["address"]
        street = fullAddr.split(",")[0]

        remainder: str = fullAddr[fullAddr.index(", ") + 2 : len(fullAddr) + 1]
        city = remainder.split(", ")[0]
        remainder = remainder.split(", ")[1]

        if " " in remainder:
            state = remainder.split(" ")[0]
            zip = remainder.split(" ")[1]
        else:
            state = remainder

    delimeters: list = [ " APT ", " UNIT ", " #" ]
    for delim in delimeters:
        if delim in street:
            index = street.index(delim)
            unit = street[index + 1 : len(street) + 1].strip()
            street = street[0 : index].strip()
            break


    return Address(
        street=street,
        unit=unit,
        city=city,
        state=state,
        zip=zip
    )

@staticmethod
def _parse_lot_sqft(result: dict):
    if ("hdpData" not in result or
        "homeInfo" not in result["hdpData"] or
        "lotAreaValue" not in result["hdpData"]["homeInfo"] or
        "lotAreaUnit" not in result["hdpData"]["homeInfo"]):
        return 0

    area = result["hdpData"]["homeInfo"]["lotAreaValue"]
    units = result["hdpData"]["homeInfo"]["lotAreaUnit"]

    if units == "sqft":
        return area
    elif units == "acres":
        return area * 43560
    else:
        raise Exception("Unable to parse lot sqft, unknown unit: {}".format(units))

@staticmethod
def _parse_list_date(timeOnZillow: int):
    # timeOnZillow represented in ms, convert to seconds
    timeOnZillow /= 1000

    # Calculate the duration represented by timeOnZillow
    duration = datetime.timedelta(seconds=timeOnZillow)

    # Calculate the date when the property was posted on the site
    currentDate = datetime.datetime.now(datetime.timezone.utc)
    return (currentDate - duration).strftime("%Y-%m-%d")
