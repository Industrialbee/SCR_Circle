import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger(__name__)

H2_PREFIX_RE = re.compile(r"^\s*\d+\.\s*")  # "1. Operator Name" -> "Operator Name"
H2_NUM_RE = re.compile(r"^\s*(\d+)\.\s*") #gets the number prefix for the operator
#OP_COLOR_TEXT_RE = re.compile(r"\bcolor\s+is\s+(#[0-9A-Fa-f]{6})\b")
OP_COLOR_TEXT_RE = re.compile(r"\bColou?r\s+(is\s+)?+(#[0-9A-Fa-f]{6})\b", re.IGNORECASE)
BRACKET_RE = re.compile(r"\[.*?\]")
MULTISPACE_RE = re.compile(r"\s+")
H2_Min=3 #don't want the H2 entries before 3. Stepford Connect (Outline and route map)
H2_Max=7 #don't want the H2 entries after 7. XXXX (deleted routes)


STATION_MARKER = "station name"


def build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def fetch_soup(url: str, timeout: float = 20.0) -> BeautifulSoup:
    session = build_session()
    resp = session.get(url, timeout=timeout, headers={"User-Agent": "scr-circle-map/0.1"})
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def normalise_text(s: str) -> str:
    return (s or "").strip().lower()


def clean_station_name(name: str) -> str:
    name = (name or "").strip()
    name = BRACKET_RE.sub("", name)
    name = MULTISPACE_RE.sub(" ", name).strip()
    fixes = {
        "Robinson Ways": "Robinson Way",
        "St. Helens Bridge": "St Helens Bridge",
        "Elsemere Juntion": "Elsemere Junction",
    }
    return fixes.get(name, name)


def clean_operator_name(h2: Tag) -> str:
    txt = h2.get_text(" ", strip=True)
    txt = MULTISPACE_RE.sub(" ", txt).strip()
    txt = H2_PREFIX_RE.sub("", txt).strip()
    return txt

def get_h2_number(h2: Tag) -> Optional[int]:
    txt = h2.get_text(" ", strip=True)
    m = H2_NUM_RE.match(txt)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None
    
def extract_operator_color_from_section(h2: Tag) -> str:
    node = h2.next_sibling
    while node is not None:
        if isinstance(node, Tag) and node.name == "h2":
            break

        if isinstance(node, Tag):
            text = node.get_text(" ", strip=True)
        else:
            text = str(node).strip()

        m = OP_COLOR_TEXT_RE.search(text)
        if m:
            return m.group(2)

        node = node.next_sibling

    return ""


def find_station_marker_row(rows: List[Tag]) -> Optional[int]:
    for i, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        first = normalise_text(cells[0].get_text(" ", strip=True))
        if first == STATION_MARKER:
            return i
    return None


def parse_station_table_for_pairs(table: Tag) -> List[Tuple[str, str]]:
    rows = table.find_all("tr")
    idx = find_station_marker_row(rows)
    if idx is None:
        return []

    stations: List[str] = []
    for row in rows[idx + 1 :]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        name = clean_station_name(cells[0].get_text(" ", strip=True))
        if name:
            stations.append(name)

    if len(stations) < 2:
        return []

    return list(zip(stations, stations[1:]))


def iter_h2_and_tables_in_order(container: Tag) -> Iterable[Tag]:
    for node in container.find_all(["h2", "table"]):
        yield node


def normalise_pair(a: str, b: str) -> Tuple[str, str]:
    # Undirected uniqueness (A-B same as B-A). Remove sorting if you want directional.
    return tuple(sorted((a, b)))


def scrape(url: str) -> Tuple[List[dict], List[dict]]:
    soup = fetch_soup(url)
    container = soup

    current_operator: Optional[str] = None
    current_operator_active = False  # only true for h2 sections we want to parse
    operator_to_color: Dict[str, str] = {}
    station_pairs: Set[Tuple[str, str, str]] = set()

    for node in iter_h2_and_tables_in_order(container):
        if isinstance(node, Tag) and node.name == "h2":
            h2_num = get_h2_number(node)

            # Default: not active until proven otherwise
            current_operator = None
            current_operator_active = False

            if h2_num is None or h2_num < H2_Min or h2_num>H2_Max:
                continue

            operator_name = clean_operator_name(node)
            color = extract_operator_color_from_section(node)

            if not color:
                LOG.info("Skipping H2 section %s ('%s'): no authoritative 'color is #...' text found.", h2_num, operator_name)
                continue

            current_operator = operator_name
            current_operator_active = True
            operator_to_color[current_operator] = color
            continue

        if isinstance(node, Tag) and node.name == "table":
            if not current_operator_active or not current_operator:
                continue

            pairs = parse_station_table_for_pairs(node)
            if not pairs:
                continue

            for a, b in pairs:
                aa, bb = normalise_pair(a, b)
                station_pairs.add((current_operator, aa, bb))

    pairs_out = [
        {"Operator": op, "FirstStation": a, "SecondStation": b}
        for op, a, b in sorted(station_pairs)
    ]
    ops_out = [
        {"Operator": op, "Colour": col}
        for op, col in sorted(operator_to_color.items())
    ]
    return pairs_out, ops_out


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    url = (
        "https://en.namu.wiki/w/Stepford%20County%20Railway/%EC%9A%B4%ED%96%89%20%EA%B3%84%ED%86%B5"
    )

    pairs, ops = scrape(url)

    out_dir = Path("data")
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "station_pairs.json").write_text(
        json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "operators.json").write_text(
        json.dumps(ops, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    LOG.info("Wrote %d station pairs and %d operators into %s", len(pairs), len(ops), out_dir)


if __name__ == "__main__":
    main()

