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
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            key = (row[key_column]
                .replace("\u2013", "-")
                .replace("\u2014", "-")
                .replace("\u2011", "-")
                .strip())
            parts = re.split(r"\s*-\s*", key)
            if len(parts) >= 2:
                city, state, submkt = parts[-3], parts[-2], parts[-1]
                d[(state.upper(), submkt)].append(row)
    return d

def lookup(d, query):
    parts = [p.strip() for p in query['location'].split(":")]
    if len(parts) != 2: return None
    state, submkt = parts
    best = None
    for (s, pat), rows in d.items():
        if s != state:
            continue
        if pat == submkt:
            score = (3, len(pat))
        elif pat and pat in submkt:
            score = (2, len(pat))
        elif submkt and submkt in pat:
            score = (1, len(pat))
        else:
            continue
        if best is None or score > best[:2]:
            best = (*score, pat, rows)
    if best:
        _,_, best_key, rows = best
        query['submarket'] = best_key
        return rows
    return [None]

def extract_submarket(raw, market):
    wrap_pat = re.compile(rf"(?mx)^\s*{re.escape(market)}\s-\s*(?P<first>[A-Za-z][A-Za-z\s/&s/&'.-]*?)\s+\d[^\n]*\n(?P<cont>[A-Za-z\s/&'.-]*?)\s+Submarket\b", re.IGNORECASE)
    m = wrap_pat.search(raw)
    if m:
        return re.sub(r"\s+", " ", f"{m.group('first')} {m.group('cont')}").strip()
    simple_pat = re.compile(
            rf"""(?mx)
            ^\s*{re.escape(market)}\s*-\s*
            (?P<sm>[A-Za-z][A-Za-z\s/&'.-]*?)
            (?=\s+\d|\s+Submarket\b|$)
            """
            , re.IGNORECASE
        )    
    m = simple_pat.search(raw)
    if m:
        return re.sub(r"\s+", " ", m.group("sm")).strip()
    return None

def parse_location(path):
    p2 = ''
    with pp.open(path) as pdf:
        raw = pdf.pages[0].extract_text() or ''
        for i in range(1, len(pdf.pages)):
            if "Submarket Cluster" in pdf.pages[i].extract_text() or '':
                p2 = pdf.pages[i].extract_text() or ''
                break
    if p2 == '' and "Submarket Cluster" in raw:
        p2 = raw
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip]
    page2 = [ln.strip() for ln in p2.splitlines() if ln.strip]
    address = path.split('_ ')[1].split('.pdf')[0]
    overview = {'address': address, 'Lease Expiration': None, 'Current Rent': None, 'city': None}
    vacant = 0
    service = ''
    propType = ''
    if 'Submarket Cluster' not in raw and "Submarket Cluster" not in p2:
        overview['submarket'] = ''

    for i in lines:
        if re.search(r'^(.*?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)', i) and not overview['city']:
            city, state, zip = re.search(r'^(.*?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)', i).groups()
            overview['city'] = city
            overview['state'] = state
        if 'RBA' in i and re.search(r"RBA\s+([\d,]+)\s+SF", i):
            overview['RBA'] = int(re.search(r"RBA\s+([\d,]+)\s+SF", i).group(1).replace(",",''))

        if 'GLA' in i and re.search(r"GLA\s+([\d,]+)\s+SF", i):
            overview['RBA'] = int(re.search(r"GLA\s+([\d,]+)\s+SF", i).group(1).replace(",",''))

        if "Recorded Owner" in i:
            if "True Owner" in lines[lines.index(i)+1]:
                overview['Landlord'] = lines[lines.index(i)+1].split("True Owner ")[1:][0]
            else:
                overview['Landlord'] = i.split("Recorded Owner ")[1:][0]
        if 'Type' in i and "Star" in i and ('Industrial' in i or 'Retail' in i or 'Office' in i or 'Flex' in i) and propType == '':
            propType = re.search(r"Star\s+(.*?)(?=\s*(?:%|Rent|Vacant|Vacancy|Sign|Subject))", i)
            if propType == None:
                propType = i.split("Star ")[1]
            else:
                propType = re.search(r"Star\s+(.*?)(?=\s*(?:%|Rent|Vacant|Vacancy|Sign|Subject))", i).group(1)

        if 'Vacant' in i:
            vacant = int(re.search(r"(\d{1,3}(?:,\d{3})*)\s*(SF)", i).group(1).replace(",", ''))

        if 'Class' in i:
            classType = re.search(r"\bClass\s+([A-Z])\b\s*", i).group(1)
            overview['Class'] = f'{classType} - {propType}'
            
        if 'Rent $' in i:
            rent = i.split('Rent ')[1]

        if 'Service Type' in i:
            service = i.split('Service Type ')[1]
    overview['Occupied SF'] = f'{overview['RBA'] - vacant} SF'
    overview['% Occupied'] = f'{100-round(vacant/overview['RBA']*100,2)}%'
    overview['Building Vacancy %'] = f'{round(vacant/overview['RBA']*100,2)} %'
    overview['RBA'] = f'{int(overview['RBA']):,}'
    if service != '':
        overview['Asking Rent'] = f'{rent} PSF {service}'
    else:
        overview['Asking Rent'] = "Fully leased building"
    for i in page2:
        if p2 == '':
            overview['submarket'] = ''
        elif 'Submarket' in i:
            overview['submarket'] = re.search(r"Submarket\s+(?!Cluster\b|SF\b|\d+(?:\s*[-–—]\s*\d+)?\s*Stars?\b|Sales\b|Leasing\b|\d+)(.+)", p2)[0].split('Submarket ')[1]
    overview['location'] = f'{overview['state']} USA : {overview['submarket']}'
    if propType.split(" ")[0] == "Office":
        submarketData = 'OfficeSubmarkets.csv'
    if propType.split(" ")[0] == 'Retail':
        submarketData = 'RetailSubmarkets.csv'
    elif propType.split(" ")[0] == "Industrial" or propType.split(" ")[0] == "Flex":
        submarketData = 'IndustrialSubmarkets.csv'
    if overview['submarket'] != '' and propType != '':
        submarkets = build_dict(submarketData, 'Geography Name')
        market = lookup(submarkets, overview)[0]
        if market != None:
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
            overview['Market Asking Rent/SF'] = f'{overview['Market Asking Rent/SF']} PSF'
    overview['Lease Expiration'] = 'Company To Provide'
    overview['Current Rent'] = 'Company To Provide'
    return overview

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