"""Deterministic simulated world the toy agent operates in.

Everything here is pure data / pure functions so that any step can be
re-executed bit-for-bit during replay.
"""
import hashlib

CITIES = {
    "Paris": "EUR", "Berlin": "EUR", "London": "GBP", "Tokyo": "JPY",
    "Mumbai": "INR", "Dubai": "AED", "Singapore": "SGD", "Toronto": "CAD",
    "Sydney": "AUD", "New York": "USD",
}
ORIGINS = ["New York", "London", "Mumbai", "Singapore", "Toronto"]

# current FX rates: 1 unit of currency -> USD
FX_TO_USD = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067, "INR": 0.012,
    "AED": 0.272, "SGD": 0.74, "CAD": 0.73, "AUD": 0.66,
}

# hotel -> (city, nightly rate in local currency, city tax, breakfast)
HOTELS = {
    "Hotel Lumiere": ("Paris", 180, 4, 22),
    "Le Petit Quai": ("Paris", 135, 3, 18),
    "Spree Residenz": ("Berlin", 120, 5, 16),
    "Mitte Loft": ("Berlin", 95, 4, 14),
    "Thames View": ("London", 210, 0, 19),
    "Camden Rooms": ("London", 140, 0, 15),
    "Kirin Inn": ("Tokyo", 18000, 300, 2200),
    "Shinjuku Tower": ("Tokyo", 26000, 400, 3100),
    "Marine Palace": ("Mumbai", 9500, 900, 1200),
    "Bandra House": ("Mumbai", 6200, 600, 800),
    "Creek Suites": ("Dubai", 650, 20, 85),
    "Palm Court": ("Dubai", 900, 25, 110),
    "Orchard Stay": ("Singapore", 280, 10, 32),
    "Marina Nest": ("Singapore", 360, 12, 38),
    "Maple Grand": ("Toronto", 240, 8, 24),
    "Harbour Lofts": ("Sydney", 260, 0, 28),
    "Bondi Retreat": ("Sydney", 310, 0, 30),
    "Hudson Point": ("New York", 320, 18, 30),
}

PER_DIEM_USD = {
    "Paris": 95, "Berlin": 80, "London": 105, "Tokyo": 90, "Mumbai": 45,
    "Dubai": 85, "Singapore": 88, "Toronto": 75, "Sydney": 92, "New York": 110,
}
TAXI_LOCAL = {
    "Paris": 55, "Berlin": 45, "London": 60, "Tokyo": 9000, "Mumbai": 1500,
    "Dubai": 120, "Singapore": 45, "Toronto": 70, "Sydney": 75, "New York": 80,
}


def _h(*parts):
    return int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest(), 16)


def flight_price_usd(src, dst):
    if src == dst:
        return 0.0
    a, b = sorted([src, dst])
    return float(180 + _h(a, b) % 900)


def hotel_doc(hotel):
    city, rate, tax, bfast = HOTELS[hotel]
    cur = CITIES[city]
    return (f"{hotel}, {city}. Standard room: {rate} {cur} per night. "
            f"City tax: {tax} {cur} per night. Breakfast: {bfast} {cur} per person. "
            f"Check-in from 15:00, check-out by 11:00. Free cancellation up to 48h.")


def hotels_in(city):
    return [h for h, v in HOTELS.items() if v[0] == city]
