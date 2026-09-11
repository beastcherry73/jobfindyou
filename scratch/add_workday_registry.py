"""Merge the verified Workday employers into backend/data/ats_companies.json.

Every entry below answered the keyless CXS endpoint with live postings on
2026-09-11 (discovery probe: 73 of 129 candidates). Five that answered were
deliberately LEFT OUT -- CVS Health, Lowe's, Home Depot, T-Mobile, AT&T --
because their boards are overwhelmingly store-floor, driver and retail roles
(e.g. "Shift Supervisor", "CDL Delivery Driver"). Real jobs, but not what a
resume-optimisation product's users are searching for, and at 18k / 12k open
roles they would drown every other employer on the board.

Idempotent: existing workday entries are replaced, nothing else is touched.

    python scratch/add_workday_registry.py
"""
import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, "backend", "data", "ats_companies.json")

# (company, tenant, pod, site, domain)
WORKDAY = [
    ("PwC", "pwc", "wd3", "Global_Experienced_Careers", "pwc.com"),
    ("Micron", "micron", "wd1", "External", "micron.com"),
    ("Thermo Fisher Scientific", "thermofisher", "wd5", "ThermoFisherCareers", "thermofisher.com"),
    ("NVIDIA", "nvidia", "wd5", "NVIDIAExternalCareerSite", "nvidia.com"),
    ("Accenture", "accenture", "wd103", "AccentureCareers", "accenture.com"),
    ("Citi", "citi", "wd5", "2", "citi.com"),
    ("Target", "target", "wd5", "targetcareers", "target.com"),
    ("JLL", "jll", "wd1", "jllcareers", "jll.com"),
    ("Abbott", "abbott", "wd5", "abbottcareers", "abbott.com"),
    ("Capital One", "capitalone", "wd12", "Capital_One", "capitalone.com"),
    ("Amgen", "amgen", "wd1", "Careers", "amgen.com"),
    ("Salesforce", "salesforce", "wd12", "External_Career_Site", "salesforce.com"),
    ("Maersk", "maersk", "wd3", "Maersk_Careers", "maersk.com"),
    ("Danaher", "danaher", "wd1", "DanaherJobs", "danaher.com"),
    ("U.S. Bank", "usbank", "wd1", "US_Bank_Careers", "usbank.com"),
    ("State Street", "statestreet", "wd1", "Global", "statestreet.com"),
    ("Verizon", "verizon", "wd12", "verizon-careers", "verizon.com"),
    ("AstraZeneca", "astrazeneca", "wd3", "Careers", "astrazeneca.com"),
    ("Medtronic", "medtronic", "wd1", "MedtronicCareers", "medtronic.com"),
    ("Deutsche Bank", "db", "wd3", "DBWebsite", "db.com"),
    ("Mastercard", "mastercard", "wd1", "CorporateCareers", "mastercard.com"),
    ("Barclays", "barclays", "wd3", "External_Career_Site_Barclays", "barclays.com"),
    ("Kyndryl", "kyndryl", "wd5", "KyndrylProfessionalCareers", "kyndryl.com"),
    ("KLA", "kla", "wd1", "Search", "kla.com"),
    ("Novartis", "novartis", "wd3", "Novartis_Careers", "novartis.com"),
    ("Motorola Solutions", "motorolasolutions", "wd5", "Careers", "motorolasolutions.com"),
    ("HP", "hp", "wd5", "ExternalCareerSite", "hp.com"),
    ("Sanofi", "sanofi", "wd3", "SanofiCareers", "sanofi.com"),
    ("Philips", "philips", "wd3", "jobs-and-careers", "philips.com"),
    ("Analog Devices", "analogdevices", "wd1", "External", "analog.com"),
    ("Nike", "nike", "wd1", "nke", "nike.com"),
    ("NXP Semiconductors", "nxp", "wd3", "careers", "nxp.com"),
    ("Gartner", "gartner", "wd5", "EXT", "gartner.com"),
    ("Adobe", "adobe", "wd5", "external_experienced", "adobe.com"),
    ("LSEG", "lseg", "wd3", "Careers", "lseg.com"),
    ("Boeing", "boeing", "wd1", "EXTERNAL_CAREERS", "boeing.com"),
    ("GSK", "gsk", "wd5", "GSKCareers", "gsk.com"),
    ("GlobalFoundries", "globalfoundries", "wd1", "External", "gf.com"),
    ("3M", "3m", "wd1", "Search", "3m.com"),
    ("Fidelity Investments", "fmr", "wd1", "FidelityCareers", "fidelity.com"),
    ("Disney", "disney", "wd5", "disneycareer", "disney.com"),
    ("Cadence", "cadence", "wd1", "External_Careers", "cadence.com"),
    ("Intel", "intel", "wd1", "External", "intel.com"),
    ("Pfizer", "pfizer", "wd1", "PfizerCareers", "pfizer.com"),
    ("Baker Hughes", "bakerhughes", "wd5", "BakerHughes", "bakerhughes.com"),
    ("Regeneron", "regeneron", "wd1", "Careers", "regeneron.com"),
    ("McKesson", "mckesson", "wd3", "External_Careers", "mckesson.com"),
    ("Gilead Sciences", "gilead", "wd1", "gileadcareers", "gilead.com"),
    ("FIS", "fis", "wd5", "SearchJobs", "fisglobal.com"),
    ("Autodesk", "autodesk", "wd1", "Ext", "autodesk.com"),
    ("CrowdStrike", "crowdstrike", "wd5", "crowdstrikecareers", "crowdstrike.com"),
    ("Workday", "workday", "wd5", "Workday", "workday.com"),
    ("Broadcom", "broadcom", "wd1", "External_Career", "broadcom.com"),
    ("Humana", "humana", "wd5", "Humana_External_Career_Site", "humana.com"),
    ("Warner Bros. Discovery", "warnerbros", "wd5", "global", "wbd.com"),
    ("BlackRock", "blackrock", "wd1", "BlackRock_Professional", "blackrock.com"),
    ("Equinix", "equinix", "wd1", "External", "equinix.com"),
    ("Elevance Health", "elevancehealth", "wd1", "ANT", "elevancehealth.com"),
    ("Nasdaq", "nasdaq", "wd1", "Global_External_Site", "nasdaq.com"),
    ("Shell", "shell", "wd3", "ShellCareers", "shell.com"),
    ("Illumina", "illumina", "wd1", "illumina-careers", "illumina.com"),
    ("Red Hat", "redhat", "wd5", "jobs", "redhat.com"),
    ("Ciena", "ciena", "wd5", "Careers", "ciena.com"),
    ("Chevron", "chevron", "wd5", "jobs", "chevron.com"),
    ("PayPal", "paypal", "wd1", "jobs", "paypal.com"),
    ("Zoetis", "zoetis", "wd5", "zoetis", "zoetis.com"),
    ("Zillow", "zillow", "wd5", "Zillow_Group_External", "zillow.com"),
    ("Sony", "sonyglobal", "wd1", "SonyGlobalCareers", "sony.com"),
]


def main():
    with open(REGISTRY, encoding="utf-8") as f:
        data = json.load(f)
    companies = [c for c in data.get("companies", []) if c.get("platform") != "workday"]
    for company, tenant, pod, site, domain in WORKDAY:
        companies.append({
            "platform": "workday",
            "token": f"{tenant}|{pod}|{site}",
            "company": company,
            "candidate": company,
            "region": "global",
            "domain": domain,
            "sample_url": f"https://{tenant}.{pod}.myworkdayjobs.com/en-US/{site}",
        })
    data["companies"] = companies
    data["workday_added_at"] = datetime.now(timezone.utc).isoformat()
    with open(REGISTRY, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"registry now {len(companies)} companies "
          f"({len(WORKDAY)} workday)")


if __name__ == "__main__":
    main()
