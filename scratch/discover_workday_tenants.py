"""Discover live Workday career sites, empirically.

Workday's keyless CXS endpoint needs BOTH a pod (wd1, wd3, wd5 ...) and a
site name, and the site name is chosen by the employer, so it cannot be
derived from the company name. There is no cheap discovery signal either: the
tenant root answers 406 for every host, real or invented (checked
2026-09-12), so the only honest method is to probe (pod, site) pairs and keep
what actually answers with live jobs.

That is bounded by probing in a deliberate order -- the pods and site names
that real employers use most, first -- and stopping at the first hit per
tenant. A tenant that exists is usually found in a handful of requests; only
the misses pay the full grid.

Output: scratch/workday_discovered.json, merged into the registry by
scratch/add_workday_registry.py.

    python scratch/discover_workday_tenants.py            # full probe
    python scratch/discover_workday_tenants.py --limit 40 # first 40 tenants
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "workday_discovered.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobSpike/1.0; +https://www.jobspike.in)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
TIMEOUT = 12
# Ordered by how often real employers sit on them.
PODS = ["wd1", "wd5", "wd3", "wd12", "wd103", "wd2", "wd10"]
# Ordered by observed frequency across the 73 tenants already confirmed.
SITE_PATTERNS = [
    "External", "ExternalCareerSite", "External_Career_Site", "Careers",
    "careers", "{T}Careers", "{t}", "jobs", "Jobs", "External_Careers",
    "ExternalCareers", "Global", "{T}_Careers", "CareerSite", "Search",
    "{T}ExternalCareerSite", "professional", "2",
    # Wave 2. Every one of these is a shape actually observed on a live
    # tenant during wave 1 (Cisco_Careers, SantanderCareers, PPG_Careers,
    # Blackstone_Careers), generalised. Several wave-1 misses used all 46
    # attempts, which says the tenant exists but its site name was outside
    # the list rather than that the employer is absent.
    "{t}careers", "{t}_careers", "{T}_External", "{T}External",
    "GlobalCareers", "Global_Careers", "Careers_External", "ExternalSite",
    "External_Site", "Corporate", "Recruiting", "Talent", "talent",
    "{T}_Careers_External", "{T}JobSite", "careersite", "CareersSite",
]
MAX_ATTEMPTS = 70          # wider grid; misses cost more, hits are worth it

# (tenant slug, display name). Tenant slugs are the subdomain, which is
# usually the company's short name -- candidates only; the probe decides.
TENANTS = [
    ("tcs", "TCS"), ("infosys", "Infosys"), ("wipro", "Wipro"), ("hcl", "HCL"),
    ("techmahindra", "Tech Mahindra"), ("ltimindtree", "LTIMindtree"),
    ("mphasis", "Mphasis"), ("hexaware", "Hexaware"), ("zensar", "Zensar"),
    ("birlasoft", "Birlasoft"), ("coforge", "Coforge"), ("cybage", "Cybage"),
    ("persistent", "Persistent Systems"), ("sonata", "Sonata Software"),
    ("happiestminds", "Happiest Minds"), ("newgen", "Newgen Software"),
    ("ramco", "Ramco Systems"), ("nucleus", "Nucleus Software"),
    ("hdfcbank", "HDFC Bank"), ("icicibank", "ICICI Bank"), ("axisbank", "Axis Bank"),
    ("kotak", "Kotak Mahindra"), ("yesbank", "Yes Bank"), ("idfcfirst", "IDFC First"),
    ("bajajfinserv", "Bajaj Finserv"), ("sbi", "SBI"), ("pnb", "PNB"),
    ("reliance", "Reliance"), ("jio", "Jio"), ("adani", "Adani"),
    ("tatamotors", "Tata Motors"), ("tatasteel", "Tata Steel"),
    ("mahindra", "Mahindra"), ("bajajauto", "Bajaj Auto"), ("heromotocorp", "Hero MotoCorp"),
    ("maruti", "Maruti Suzuki"), ("ashokleyland", "Ashok Leyland"),
    ("godrej", "Godrej"), ("itc", "ITC"), ("dabur", "Dabur"), ("marico", "Marico"),
    ("britannia", "Britannia"), ("nestle", "Nestle"), ("unilever", "Unilever"),
    ("pg", "Procter and Gamble"), ("colgate", "Colgate"), ("loreal", "LOreal"),
    ("cipla", "Cipla"), ("drreddys", "Dr Reddys"), ("sunpharma", "Sun Pharma"),
    ("lupin", "Lupin"), ("biocon", "Biocon"), ("torrent", "Torrent Pharma"),
    ("glenmark", "Glenmark"), ("zyduslife", "Zydus"), ("aurobindo", "Aurobindo"),
    ("apollohospitals", "Apollo Hospitals"), ("fortishealthcare", "Fortis"),
    ("maxhealthcare", "Max Healthcare"), ("narayanahealth", "Narayana Health"),
    ("deloitte", "Deloitte"), ("ey", "EY"), ("kpmg", "KPMG"), ("bain", "Bain"),
    ("mckinsey", "McKinsey"), ("bcg", "BCG"), ("zs", "ZS Associates"),
    ("cognizant", "Cognizant"), ("capgemini", "Capgemini"), ("dxc", "DXC"),
    ("atos", "Atos"), ("ntt", "NTT Data"), ("fujitsu", "Fujitsu"),
    ("unisys", "Unisys"), ("virtusa", "Virtusa"), ("syntel", "Syntel"),
    ("ibm", "IBM"), ("microsoft", "Microsoft"), ("oracle", "Oracle"),
    ("sap", "SAP"), ("cisco", "Cisco"), ("dellcareers", "Dell"),
    ("hpe", "HPE"), ("lenovo", "Lenovo"), ("samsung", "Samsung"),
    ("lg", "LG Electronics"), ("sony", "Sony"), ("panasonic", "Panasonic"),
    ("siemens", "Siemens"), ("bosch", "Bosch"), ("abb", "ABB"),
    ("schneider", "Schneider Electric"), ("honeywell", "Honeywell"),
    ("ge", "GE"), ("emerson", "Emerson"), ("rockwell", "Rockwell Automation"),
    ("johnsoncontrols", "Johnson Controls"), ("carrier", "Carrier"),
    ("trane", "Trane Technologies"), ("dover", "Dover Corporation"),
    ("parker", "Parker Hannifin"), ("eaton", "Eaton"), ("cummins", "Cummins"),
    ("deere", "John Deere"), ("cat", "Caterpillar"), ("volvo", "Volvo"),
    ("daimler", "Daimler"), ("bmwgroup", "BMW Group"), ("vw", "Volkswagen"),
    ("ford", "Ford"), ("gm", "General Motors"), ("stellantis", "Stellantis"),
    ("nissan", "Nissan"), ("toyota", "Toyota"), ("honda", "Honda"),
    ("hyundai", "Hyundai"), ("kia", "Kia"), ("tesla", "Tesla"),
    ("rivian", "Rivian"), ("lucidmotors", "Lucid Motors"),
    ("jpmorgan", "JPMorgan"), ("morganstanley", "Morgan Stanley"),
    ("goldmansachs", "Goldman Sachs"), ("bofa", "Bank of America"),
    ("wellsfargo2", "Wells Fargo"), ("hsbc", "HSBC"), ("standardchartered", "Standard Chartered"),
    ("barclays2", "Barclays"), ("ubs", "UBS"), ("creditsuisse", "Credit Suisse"),
    ("db2", "Deutsche Bank"), ("santander", "Santander"), ("bnpparibas", "BNP Paribas"),
    ("socgen", "Societe Generale"), ("natwest", "NatWest"), ("lloyds", "Lloyds"),
    ("rbc", "RBC"), ("td", "TD Bank"), ("scotiabank", "Scotiabank"),
    ("bmo", "BMO"), ("cibc", "CIBC"), ("anz", "ANZ"), ("nab", "NAB"),
    ("westpac", "Westpac"), ("commbank", "Commonwealth Bank"),
    ("macquarie", "Macquarie"), ("allianz", "Allianz"), ("axa", "AXA"),
    ("zurich", "Zurich Insurance"), ("aviva", "Aviva"), ("prudential", "Prudential"),
    ("metlife", "MetLife"), ("aig", "AIG"), ("chubb", "Chubb"),
    ("marsh", "Marsh McLennan"), ("aon", "Aon"), ("wtw", "WTW"),
    ("visa", "Visa"), ("amex", "American Express"), ("discover", "Discover"),
    ("fiserv", "Fiserv"), ("globalpayments", "Global Payments"), ("worldpay", "Worldpay"),
    ("nasdaq2", "Nasdaq"), ("cme", "CME Group"), ("ice", "ICE"),
    ("blackstone", "Blackstone"), ("kkr", "KKR"), ("apollo", "Apollo Global"),
    ("carlyle", "Carlyle"), ("brookfield", "Brookfield"),
    ("accenture2", "Accenture"), ("genpact2", "Genpact"), ("wns2", "WNS"),
    ("firstsource", "Firstsource"), ("teleperformance", "Teleperformance"),
    ("concentrix2", "Concentrix"), ("sutherland", "Sutherland"),
    ("amazon", "Amazon"), ("walmart2", "Walmart"), ("target2", "Target"),
    ("costco", "Costco"), ("kroger", "Kroger"), ("albertsons", "Albertsons"),
    ("tjx", "TJX"), ("ross", "Ross Stores"), ("gap", "Gap"), ("nordstrom", "Nordstrom"),
    ("macys", "Macys"), ("kohls", "Kohls"), ("bestbuy", "Best Buy"),
    ("starbucks", "Starbucks"), ("mcdonalds", "McDonalds"), ("yum", "Yum Brands"),
    ("chipotle", "Chipotle"), ("dominos", "Dominos"), ("darden", "Darden"),
    ("marriott2", "Marriott"), ("hilton2", "Hilton"), ("hyatt", "Hyatt"),
    ("ihg", "IHG"), ("accor", "Accor"), ("wyndham", "Wyndham"),
    ("delta", "Delta Air Lines"), ("united", "United Airlines"),
    ("aa", "American Airlines"), ("southwest", "Southwest Airlines"),
    ("lufthansa", "Lufthansa"), ("britishairways", "British Airways"),
    ("emirates", "Emirates"), ("qatarairways", "Qatar Airways"),
    ("singaporeair", "Singapore Airlines"), ("cathaypacific", "Cathay Pacific"),
    ("fedex", "FedEx"), ("ups", "UPS"), ("dhl", "DHL"), ("dbschenker", "DB Schenker"),
    ("kuehnenagel", "Kuehne Nagel"), ("dsv", "DSV"), ("expeditors", "Expeditors"),
    ("pepsi", "PepsiCo"), ("cocacola", "Coca Cola"), ("kraftheinz", "Kraft Heinz"),
    ("generalmills2", "General Mills"), ("kellogg", "Kellanova"), ("mars", "Mars"),
    ("mondelez2", "Mondelez"), ("danone", "Danone"), ("abinbev", "AB InBev"),
    ("diageo", "Diageo"), ("heineken", "Heineken"), ("pernodricard", "Pernod Ricard"),
    ("merck", "Merck"), ("pfizer2", "Pfizer"), ("jnj2", "Johnson and Johnson"),
    ("roche", "Roche"), ("bayer", "Bayer"), ("boehringer", "Boehringer Ingelheim"),
    ("takeda", "Takeda"), ("amgen2", "Amgen"), ("moderna", "Moderna"),
    ("biontech", "BioNTech"), ("csl", "CSL"), ("baxter", "Baxter"),
    ("becton", "BD"), ("stryker", "Stryker"), ("zimmer", "Zimmer Biomet"),
    ("edwards", "Edwards Lifesciences"), ("intuitive", "Intuitive Surgical"),
    ("agilent", "Agilent"), ("waters", "Waters Corporation"), ("perkinelmer", "PerkinElmer"),
    ("bruker", "Bruker"), ("qiagen", "QIAGEN"), ("bio-rad", "Bio Rad"),
    ("exxonmobil", "ExxonMobil"), ("bp", "BP"), ("totalenergies", "TotalEnergies"),
    ("equinor", "Equinor"), ("eni", "Eni"), ("halliburton", "Halliburton"),
    ("slb2", "SLB"), ("weatherford", "Weatherford"), ("nov", "NOV"),
    ("dow", "Dow"), ("dupont", "DuPont"), ("basf", "BASF"), ("linde", "Linde"),
    ("airliquide", "Air Liquide"), ("ecolab", "Ecolab"), ("ppg", "PPG"),
    ("sherwinwilliams", "Sherwin Williams"), ("albemarle", "Albemarle"),
    ("arcelormittal", "ArcelorMittal"), ("nucor", "Nucor"), ("alcoa", "Alcoa"),
    ("riotinto", "Rio Tinto"), ("bhp", "BHP"), ("glencore", "Glencore"),
    ("vale", "Vale"), ("freeport", "Freeport McMoRan"), ("newmont", "Newmont"),
    ("aecom", "AECOM"), ("jacobs", "Jacobs"), ("fluor", "Fluor"),
    ("bechtel", "Bechtel"), ("wsp", "WSP"), ("arcadis", "Arcadis"),
    ("stantec", "Stantec"), ("ghd", "GHD"), ("mottmac", "Mott MacDonald"),
    ("cbre", "CBRE"), ("jll2", "JLL"), ("cushwake", "Cushman Wakefield"),
    ("colliers", "Colliers"), ("savills", "Savills"), ("knightfrank", "Knight Frank"),
    ("publicis", "Publicis"), ("wpp", "WPP"), ("omnicom", "Omnicom"),
    ("dentsu", "Dentsu"), ("ipg", "Interpublic"), ("havas", "Havas"),
    ("nielsen", "Nielsen"), ("kantar", "Kantar"), ("ipsos", "Ipsos"),
    ("gartner2", "Gartner"), ("forrester", "Forrester"), ("idc", "IDC"),
    ("thomsonreuters", "Thomson Reuters"), ("relx", "RELX"), ("wolterskluwer", "Wolters Kluwer"),
    ("pearson", "Pearson"), ("mcgrawhill", "McGraw Hill"), ("cengage", "Cengage"),
    ("chegg", "Chegg"), ("coursera", "Coursera"), ("udemy", "Udemy"),
    ("2u", "2U"), ("instructure", "Instructure"), ("powerschool", "PowerSchool"),
    ("workdayinc", "Workday"), ("salesforce2", "Salesforce"), ("adobe2", "Adobe"),
    ("intuit", "Intuit"), ("servicenow", "ServiceNow"), ("splunk", "Splunk"),
    ("vmware2", "VMware"), ("nutanix2", "Nutanix"), ("purestorage", "Pure Storage"),
    ("netapp2", "NetApp"), ("westerndigital", "Western Digital"), ("seagate", "Seagate"),
    ("amd2", "AMD"), ("arm2", "Arm"), ("marvell", "Marvell"), ("skyworks", "Skyworks"),
    ("qorvo", "Qorvo"), ("onsemi", "onsemi"), ("infineon", "Infineon"),
    ("stmicro", "STMicroelectronics"), ("renesas", "Renesas"), ("tsmc", "TSMC"),
    ("umc", "UMC"), ("asml", "ASML"), ("lamresearch", "Lam Research"),
    ("appliedmaterials", "Applied Materials"), ("teradyne", "Teradyne"),
    ("keysight", "Keysight"), ("nvidia2", "NVIDIA"), ("qualcomm2", "Qualcomm"),
    ("texasinstruments", "Texas Instruments"), ("microchip", "Microchip"),

    # ── Wave 2 candidates ─────────────────────────────────────────────────
    ("intuit2", "Intuit"), ("ebay", "eBay"), ("visa2", "Visa"),
    ("starbucks2", "Starbucks"), ("adp", "ADP"), ("paychex", "Paychex"),
    ("equifax", "Equifax"), ("experian", "Experian"), ("transunion", "TransUnion"),
    ("fico", "FICO"), ("msci", "MSCI"), ("cboe", "Cboe"), ("factset", "FactSet"),
    ("morningstar", "Morningstar"), ("sp", "S and P Global"),
    ("sysco", "Sysco"), ("aramark", "Aramark"), ("compassgroup", "Compass Group"),
    ("performancefood", "Performance Food Group"), ("usfoods", "US Foods"),
    ("wipro2", "Wipro"), ("lti", "LTIMindtree"), ("mindtree", "Mindtree"),
    ("lntinfotech", "LTI"), ("zensar2", "Zensar"), ("firstsource2", "Firstsource"),
    ("tataconsumer", "Tata Consumer"), ("titan", "Titan Company"),
    ("vedanta", "Vedanta"), ("jswsteel", "JSW Steel"), ("hindalco", "Hindalco"),
    ("ultratech", "UltraTech Cement"), ("ambuja", "Ambuja Cements"),
    ("larsentoubro", "Larsen and Toubro"), ("siemensenergy", "Siemens Energy"),
    ("vestas", "Vestas"), ("ge-vernova", "GE Vernova"), ("gehealthcare2", "GE HealthCare"),
    ("philips2", "Philips"), ("elekta", "Elekta"), ("getinge", "Getinge"),
    ("smithnephew", "Smith and Nephew"), ("conmed", "CONMED"),
    ("hologic", "Hologic"), ("resmed", "ResMed"), ("dexcom", "Dexcom"),
    ("insulet", "Insulet"), ("westpharma", "West Pharmaceutical"),
    ("catalent", "Catalent"), ("lonza", "Lonza"), ("sartorius", "Sartorius"),
    ("avantor", "Avantor"), ("revvity", "Revvity"), ("charlesriver", "Charles River"),
    ("iqvia", "IQVIA"), ("syneos", "Syneos Health"), ("parexel", "Parexel"),
    ("icon", "ICON plc"), ("fortrea", "Fortrea"), ("labcorp", "Labcorp"),
    ("quest", "Quest Diagnostics"), ("cardinalhealth", "Cardinal Health"),
    ("henryschein", "Henry Schein"), ("owenminor", "Owens and Minor"),
    ("cencora", "Cencora"), ("mckesson2", "McKesson"), ("elevance2", "Elevance"),
    ("centene", "Centene"), ("molina", "Molina Healthcare"), ("cigna", "Cigna"),
    ("aetna", "Aetna"), ("uhg", "UnitedHealth Group"), ("optum", "Optum"),
    ("kaiser", "Kaiser Permanente"), ("hcahealthcare", "HCA Healthcare"),
    ("tenethealth", "Tenet Healthcare"), ("chs", "Community Health Systems"),
    ("universalhealth", "Universal Health Services"), ("encompass", "Encompass Health"),
    ("davita", "DaVita"), ("fresenius", "Fresenius"), ("baxalta", "Baxalta"),
    ("zoetis2", "Zoetis"), ("idexx", "IDEXX"), ("neogen", "Neogen"),
    ("corteva", "Corteva"), ("fmc", "FMC Corporation"), ("nutrien", "Nutrien"),
    ("mosaic", "Mosaic"), ("cf", "CF Industries"), ("yara", "Yara"),
    ("adm", "ADM"), ("bunge", "Bunge"), ("cargill", "Cargill"),
    ("tyson", "Tyson Foods"), ("hormel", "Hormel"), ("conagra", "Conagra"),
    ("campbells", "Campbell Soup"), ("smucker", "JM Smucker"), ("hersheys", "Hershey"),
    ("mccormick", "McCormick"), ("churchdwight", "Church and Dwight"),
    ("cloroxcompany", "Clorox"), ("kimberlyclark", "Kimberly Clark"),
    ("estee", "Estee Lauder"), ("coty", "Coty"), ("edgewell", "Edgewell"),
    ("newellbrands", "Newell Brands"), ("stanleyblackanddecker", "Stanley Black and Decker"),
    ("masco", "Masco"), ("mohawk", "Mohawk Industries"), ("whirlpool", "Whirlpool"),
    ("electrolux", "Electrolux"), ("dyson", "Dyson"), ("sharkninja", "SharkNinja"),
    ("lego", "LEGO"), ("hasbro", "Hasbro"), ("mattel", "Mattel"),
    ("ea", "Electronic Arts"), ("ubisoft", "Ubisoft"), ("take2", "Take Two"),
    ("activision", "Activision Blizzard"), ("riotgames", "Riot Games"),
    ("epicgames", "Epic Games"), ("roblox", "Roblox"), ("unity", "Unity"),
    ("netflix", "Netflix"), ("paramount", "Paramount"), ("nbcuniversal", "NBCUniversal"),
    ("foxcorporation", "Fox Corporation"), ("sonypictures", "Sony Pictures"),
    ("lionsgate", "Lionsgate"), ("amcnetworks", "AMC Networks"),
    ("spotify2", "Spotify"), ("warnermusic", "Warner Music"), ("umg", "Universal Music"),
    ("liveNation", "Live Nation"), ("ticketmaster", "Ticketmaster"),
    ("expedia2", "Expedia"), ("booking", "Booking Holdings"), ("tripadvisor", "Tripadvisor"),
    ("airbnb", "Airbnb"), ("uber", "Uber"), ("lyft", "Lyft"), ("doordash", "DoorDash"),
    ("instacart", "Instacart"), ("grubhub", "Grubhub"), ("deliveroo", "Deliveroo"),
    ("justeattakeaway", "Just Eat Takeaway"), ("zalando2", "Zalando"),
    ("asos", "ASOS"), ("boohoo", "boohoo"), ("next", "Next plc"),
    ("marksandspencer", "Marks and Spencer"), ("tesco", "Tesco"), ("sainsburys", "Sainsburys"),
    ("morrisons", "Morrisons"), ("aldi", "Aldi"), ("lidl", "Lidl"),
    ("carrefour", "Carrefour"), ("ahold", "Ahold Delhaize"), ("metro", "METRO"),
    ("ikea", "IKEA"), ("hm", "H and M"), ("inditex", "Inditex"),
    ("adidas", "adidas"), ("puma", "PUMA"), ("underarmour", "Under Armour"),
    ("lululemon", "lululemon"), ("vfc", "VF Corporation"), ("levi", "Levi Strauss"),
    ("ralphlauren", "Ralph Lauren"), ("tapestry", "Tapestry"), ("capri", "Capri Holdings"),
    ("richemont", "Richemont"), ("lvmh", "LVMH"), ("kering", "Kering"),
    ("swarovski", "Swarovski"), ("pandora", "Pandora"), ("signet", "Signet Jewelers"),
]


def probe(session, tenant, pod, site):
    url = f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    try:
        r = session.post(url, json={"limit": 1, "offset": 0, "searchText": "",
                                    "appliedFacets": {}},
                         headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    total = data.get("total") or 0
    if not total or not (data.get("jobPostings") or []):
        return None
    return int(total)


def sites_for(tenant, name):
    camel = "".join(w[0].upper() + w[1:] for w in name.split() if w)
    out = []
    for pattern in SITE_PATTERNS:
        site = pattern.replace("{T}", camel).replace("{t}", tenant)
        if site not in out:
            out.append(site)
    return out


def discover(item):
    tenant, name = item
    session = requests.Session()
    attempts = 0
    for pod in PODS:
        for site in sites_for(tenant, name):
            if attempts >= MAX_ATTEMPTS:
                return None
            attempts += 1
            total = probe(session, tenant, pod, site)
            if total:
                return {"tenant": tenant, "company": name, "pod": pod,
                        "site": site, "jobs": total, "attempts": attempts}
    return None


def load_existing():
    """Hits from a previous run, so a second wave extends rather than redoes."""
    if not os.path.exists(OUT):
        return []
    try:
        with open(OUT, encoding="utf-8") as f:
            rows = json.load(f)
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def main():
    tenants = TENANTS
    existing = load_existing()
    found_tenants = {r.get("tenant") for r in existing}
    if existing:
        print(f"Carrying forward {len(existing)} tenants already confirmed")
        tenants = [t for t in tenants if t[0] not in found_tenants]
    if "--limit" in sys.argv:
        i = sys.argv.index("--limit")
        tenants = tenants[:int(sys.argv[i + 1])]
    print(f"Probing {len(tenants)} candidate Workday tenants "
          f"({len(PODS)} pods x {len(SITE_PATTERNS)} site patterns, first hit wins)")
    started = time.time()
    found = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for i, res in enumerate(pool.map(discover, tenants), 1):
            if res:
                found.append(res)
                print(f"  [{i:3d}/{len(tenants)}] HIT  {res['company']:26s} "
                      f"{res['tenant']}.{res['pod']} / {res['site']:28s} "
                      f"{res['jobs']:6d} jobs  ({res['attempts']} tries)")
            elif i % 25 == 0:
                print(f"  [{i:3d}/{len(tenants)}] ...")
    merged = existing + found
    print(f"\nProbed in {time.time() - started:.0f}s")
    print(f"New Workday sites found : {len(found)} / {len(tenants)} candidates probed")
    print(f"Total confirmed tenants : {len(merged)}")
    print(f"Live jobs behind them   : {sum(f['jobs'] for f in merged):,}")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=1)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
