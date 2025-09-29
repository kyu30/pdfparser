import pdfplumber as pp
import regex as re
import logging
import csv 
import os
from collections import defaultdict

ALT = {
    "center": r"(Center|Ctr|Cntr)",
    "valley": r"(Valley|Vly)",
    "mountain": r"(Mountain|Mtn)",
    "heights": r"(Heights|Hts|Hgts)",
    "parkway": r"(Parkway|Pkwy)",
    "boulevard": r"(Boulevard|Blvd)",
    "road": r"(Road|Rd)",
    "drive": r"(Drive|Dr)",
    "street": r"(Street|St)",
    "avenue": r"(Avenue|Ave)",
    "terrace": r"(Terrace|Ter|Terr)",
    "place": r"(Place|Pl)",
    "court": r"(Court|Ct)",
    "square": r"(Square|Sq)",
    "village": r"(Village|Vlg|Vill)",
    "commons": r"(Commons|Cmns)",
    "harbor": r"(Harbor|Hbr)",
    "fort": r"(Fort|Ft)",
    "point": r"(Point|Pt)",
    "mount": r"(Mount|Mt)",
    "saint": r"(Saint|St)",
    "sainte": r"(Sainte|Ste)",
    "international": r"(International|Intl|Int’l|Int'l)",
    "university": r"(University|Univ|U)",
    "industrial": r"(Industrial|Ind|Indust)",
    "business": r"(Business)",
    "district": r"(District|Dist)",
    "cbd": r"(CBD|Central Business District)",
    "north": r"(North|N)",
    "south": r"(South|S)",
    "east": r"(East|E)",
    "west": r"(West|W)",
    "county": r"(County|Co|Cnty)",
    "and": r"(and|&)",
}

PROTECT = {"street", "saint", "sainte"}
SEP = r"[\s\-\/]*"

logging.getLogger("pdfminer").setLevel(logging.ERROR)

PropertyType = ['Office', 'Industrial', 'Retail', 'Flex', 'Multi-Family', 'Student', 'Land', 'Hospitality', 'Health Care', 'Specialty', 'Sports & Entertainment']
Leases = {
    'Triple Net': 'NNN',
    'Double Net': 'NN',
    'Single Net': 'N'
}

order = ['address', 'Class', 'RBA', 'Building Vacancy %', 'Asking Rent', 'Landlord', 'Lease Expiration', '% Occupied', 'Occupied SF', 'Current Rent', 'Existing Buildings', 'Inventory SF', 'Vacancy Rate', 'Net Absorption SF 12 Mo', 'Net Delivered SF 12 Mo', 'Market Asking Rent/SF', 'city', 'state', 'submarket']

def token_regex(tok: str):
    return ALT.get(tok.lower(), re.escape(tok))
def make_pattern(submarket):
    tokens = re.findall(r"[A-Za-z0-9]+|&|[A-Za-z]+'[A-Za-z]+", submarket)
    pat = SEP.join(token_regex(t) for t in tokens)
    return re.compile(pat, re.IGNORECASE)
def build_dict(csv_path: str, key_column: str):
    d = defaultdict(list)
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            parts = [p.strip() for p in row[key_column].split("-")]
            if len(parts) >= 2:
                state, submkt = parts[-2], parts[-1]
                pat = make_pattern(submkt)
                d[(state.upper(), pat)].append(row)
    return d

def lookup(d, query: str):
    parts = [p.strip() for p in query.split("-")]
    if len(parts) != 2: return None
    state, submkt = parts
    for (s, pat), rows in d.items():
        if s == state.upper() and pat.search(submkt):
            return rows
    return None

def parse_location(path):
    with pp.open(path) as pdf:
        raw = pdf.pages[0].extract_text() or ''
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip]
    overview = {'address': lines[1], 'Lease Expiration': '', 'Current Rent': ''}
    vacant = 0
    service = ''
    for i in lines:
        if re.search(r'^(.*?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)', i):
            city, state, zip = re.search(r'^(.*?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)', i).groups()
            overview['city'] = city
            overview['state'] = state
        if 'RBA' in i and re.search(r"RBA\s+([\d,]+)\s+SF", i):
            overview['RBA'] = int(re.search(r"RBA\s+([\d,]+)\s+SF", i).group(1).replace(",",''))
        if "Recorded Owner" in i:
            if "True Owner" in lines[lines.index(i)+1]:
                overview['Landlord'] = lines[lines.index(i)+1].split("True Owner ")[1:][0]
            else:
                overview['Landlord'] = i.split("Recorded Owner ")[1:][0]
        if 'Type' in i and "Star" in i:
            propType = re.search(r"Star\s+(.*?)(?=\s*(?:%|Rent|Vacant))", i)
            if propType == None:
                propType = i.split("Star ")[1]
            else:
                propType = re.search(r"Star\s+(.*?)(?=\s*(?:%|Rent|Vacant))", i).group(1)
        if 'Vacant' in i:
            vacant = int(re.search(r"(\d{1,3}(?:,\d{3})*)\s*SF", i).group(1).replace(",", ''))
        if 'Class' in i:
            classType = re.search(r"\bClass\s+([A-Z])\b", i).group(1)
            overview['Class'] = f'{classType} - {propType}'
        if 'Rent $' in i:
            rent = i.split('Rent ')[1]
        if 'Service Type' in i:
            service = i.split('Service Type ')[1]
    overview['Occupied SF'] = f'{overview['RBA'] - vacant} SF'
    overview['% Occupied'] = f'{100-round(vacant/overview['RBA']*100,2)}%'
    overview['Building Vacancy %'] = f'{round(vacant/overview['RBA']*100,2)} %'
    if service != '':
        overview['Asking Rent'] = f'{rent} PSF {service}'
    else:
        overview['Asking Rent'] = "Fully leased building"
    pattern = r"^(?:" + "|".join(map(re.escape, PropertyType)) + r")\s+(.*)$"
    m = re.match(pattern, propType).group(1)
    overview['submarket'] = re.findall(rf"^\s*{re.escape(m)}\s*-\s*([A-Za-z][A-Za-z\s/&'.-]*?)(?=\s+\d|\s+SF|\s+Multi|$)", raw,flags =re.MULTILINE)[0]
    overview['location'] = f'{overview['state']} USA - {overview['submarket']}'
    if propType.split(" ")[0] == "Industrial":
        submarketData = 'IndustrialSubmarkets.csv'
    elif propType.split(" ")[0] == "Office" or propType.split(" ")[0] == "Flex":
        submarketData = 'OfficeSubmarkets.csv'
    submarkets = build_dict(submarketData, 'Geography Name')
    market = lookup(submarkets, overview['location'])[0]
    overview = overview | market
    if not(overview['Net Absorption SF 12 Mo']):
        overview['Net Absorption SF 12 Mo'] = '0 SF'
    elif int(overview['Net Absorption SF 12 Mo']) < 0:
        overview['Net Absorption SF 12 Mo'] = f'({int(overview['Net Absorption SF 12 Mo']):,}) SF'
    else:
        overview['Net Absorption SF 12 Mo'] = f'{int(overview['Net Absorption SF 12 Mo']):,} SF'
    if not(overview['Net Delivered SF 12 Mo']):
        overview['Net Delivered SF 12 Mo'] = '0 SF'
    elif int(overview['Net Delivered SF 12 Mo']) < 0:
        overview['Net Delivered SF 12 Mo'] = f'({int(overview['Net Delivered SF 12 Mo']):,}) SF'        
    else:
        overview['Net Delivered SF 12 Mo'] = f'{int(overview['Net Delivered SF 12 Mo']):,} SF'
    
    overview['Inventory SF'] = f'{int(overview['Inventory SF']):,}'
    overview['RBA'] = f'{int(overview['RBA']):,}'
    overview['Market Asking Rent/SF'] = f'{overview['Market Asking Rent/SF']} PSF'
    return overview
#print(parse_location("Properties _ 6500 Harbour Heights Pky - Harbour Pointe Tech Center.pdf"))
#print(parse_location("Properties _ 4440 E Elwood St - Bldg 6.pdf"))
#print(parse_location("Properties _ 7400 W Buckeye Rd.pdf"))

def main(folder, output_csv, exclude):
    if exclude is None:
        exclude = []
    results = []
    for file in os.listdir(folder):
        if file.lower().endswith(".pdf"):
            pdf_path = os.path.join(folder, file)
            try:
                data = parse_location(pdf_path)
                if isinstance(data, dict):
                    filtered = {k: v for k, v in data.items() if k not in exclude}
                    results.append(filtered)
            except Exception as e:
                print(f'Error parsing {file}: {e}')
    if results:
        fieldnames = order
        print(fieldnames)
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        print(f"Wrote {len(results)} rows to {output_csv}")
    else:
        print("No results extracted.")
if __name__ == "__main__":

    main(".", "all_results.csv", ['location', 'Geography Name', 'Property Class Name', 'Period', 'Slice', 'As Of'])