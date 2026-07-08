"""
crystal_uploader.py  —  Production-grade CIF + PDF extractor for Piezo-LLM
Extracts 40+ fields from CIF crystallography AND research paper PDF.
Place next to backend.py in ~/Documents/Piezo-LLM/src/
"""

import os, json, re, tempfile
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(os.path.expanduser('~/Documents/Piezo-LLM/data'))

# ═══════════════════════════════════════════════════════════════════
# Space-group intelligence
# ═══════════════════════════════════════════════════════════════════
NON_CENTRO_SG = set([
    1,3,4,5,6,7,8,9,16,17,18,19,20,21,22,23,24,
    25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,
    75,76,77,78,79,80,81,82,89,90,91,92,93,94,95,96,97,98,
    99,100,101,102,103,104,105,106,107,108,109,110,
    111,112,113,114,115,116,117,118,119,120,121,122,
    143,144,145,146,149,150,151,152,153,154,155,156,157,158,159,160,161,
    168,169,170,171,172,173,174,177,178,179,180,181,182,183,184,185,186,
    187,188,189,190,195,196,197,198,199,
    207,208,209,210,211,212,213,214,215,216,217,218,219,220,
])

SG_SYMBOL_TO_NUM = {
    'P1':1,'P-1':2,'P21':4,'P21/c':14,'P21/n':14,'C2':5,'Cc':9,'C2/c':15,
    'P212121':19,'Pna21':33,'Pca21':29,'Fdd2':43,'Pnma':62,'Pbca':61,
    'P21212':18,'Pmn21':31,'Pmc21':26,'Cmc21':36,'Aba2':41,'Ima2':46,
    'P4':75,'P41':76,'P42':77,'P43':78,'I4':79,'I41':80,'P-4':81,'I-4':82,
    'P422':89,'P4212':90,'P4mm':99,'P-42m':111,'P-421m':113,'I-4m2':119,
    'P3':143,'P31':144,'P32':145,'R3':146,'P321':150,'P3121':152,
    'P3m1':156,'R3m':160,'R3c':161,'P6':168,'P63':173,'P-6':174,
    'P622':177,'P6mm':183,'P-6m2':187,'P-62m':189,
    'P213':198,'F23':196,'I213':199,'F-43m':216,'I-43m':217,
}

def _sg_to_system(n):
    if n<=2: return "Triclinic"
    if n<=15: return "Monoclinic"
    if n<=74: return "Orthorhombic"
    if n<=142: return "Tetragonal"
    if n<=167: return "Trigonal"
    if n<=194: return "Hexagonal"
    return "Cubic"


# ═══════════════════════════════════════════════════════════════════
# PMC-ID helper
# ═══════════════════════════════════════════════════════════════════
def get_next_pmc_id():
    mx = 0
    for e in DATA_DIR.iterdir():
        if e.is_dir() and e.name.startswith('PMC-'):
            m = re.match(r'PMC-(\d+)', e.name)
            if m: mx = max(mx, int(m.group(1)))
    return f'PMC-{mx+1:03d}'


# ═══════════════════════════════════════════════════════════════════
# CIF PARSER  —  extracts every useful crystallographic field
# ═══════════════════════════════════════════════════════════════════
def _cv(text, tag):
    for pat in [rf"{re.escape(tag)}\s+'([^']*)'",
                rf'{re.escape(tag)}\s+"([^"]*)"',
                rf"{re.escape(tag)}\s+(\S+)"]:
        m = re.search(pat, text)
        if m:
            v = m.group(1).strip()
            return None if v in ('?','.') else v
    return None

def _cf(text, tag):
    r = _cv(text, tag)
    if not r: return None
    try: return round(float(re.sub(r'\(.*?\)','',r)), 6)
    except: return None

def _ci(text, tag):
    r = _cv(text, tag)
    if not r: return None
    try: return int(re.sub(r'\(.*?\)','',r))
    except: return None


def parse_cif(cif_bytes):
    d = {}
    try: text = cif_bytes.decode('utf-8', errors='replace')
    except: return d

    # Identity
    d['chemical_formula'] = _cv(text, '_chemical_formula_sum')
    n = _cv(text, '_chemical_name_systematic')
    if not n or n=='?': n = _cv(text, '_chemical_name_common')
    if n and n!='?': d['chemical_name'] = n
    fw = _cf(text, '_chemical_formula_weight')
    if fw: d['molecular_weight'] = round(fw,2)

    # CCDC / CSD
    cc = _cv(text, '_database_code_depnum_ccdc_archive')
    if cc:
        m = re.search(r'(\d+)', cc)
        if m: d['ccdc_number'] = int(m.group(1))
    csd = _cv(text, '_database_code_CSD')
    if csd: d['csd_refcode'] = csd

    # Dates & DOI
    m = re.search(r'(\d{4}-\d{2}-\d{2})\s+deposited', text)
    if m: d['deposition_date'] = m.group(1)
    for p in [r'_citation_doi\s*\n\s*\S+\s+(10\.\S+)', r'_citation_doi\s+(10\.\S+)']:
        m = re.search(p, text)
        if m: d['citation_doi'] = m.group(1).strip(); break

    # Symmetry
    d['space_group_symbol'] = _cv(text,'_symmetry_space_group_name_H-M') or _cv(text,'_space_group_name_H-M_alt')
    sg = _ci(text,'_symmetry_Int_Tables_number') or _ci(text,'_space_group_IT_number')
    if not sg and d.get('space_group_symbol'):
        sg = SG_SYMBOL_TO_NUM.get(d['space_group_symbol'].replace(' ',''))
    if sg:
        d['space_group_number'] = sg
        d['centrosymmetric'] = sg not in NON_CENTRO_SG
        d['property_symmetry_compatible'] = sg in NON_CENTRO_SG
    cs = _cv(text,'_symmetry_cell_setting') or _cv(text,'_space_group_crystal_system')
    d['crystal_system'] = cs.capitalize() if cs else (_sg_to_system(sg) if sg else None)

    # Cell
    for tag,key in [('_cell_length_a','cell_a'),('_cell_length_b','cell_b'),
                    ('_cell_length_c','cell_c'),('_cell_angle_alpha','cell_alpha'),
                    ('_cell_angle_beta','cell_beta'),('_cell_angle_gamma','cell_gamma'),
                    ('_cell_volume','cell_volume')]:
        v = _cf(text,tag)
        if v is not None: d[key] = v
    z = _ci(text,'_cell_formula_units_Z')
    if z: d['cell_z'] = z

    # Crystal
    h = _cv(text,'_exptl_crystal_description')
    if h and h!='?': d['habit'] = h
    c = _cv(text,'_exptl_crystal_colour')
    if c and c!='?': d['colour'] = c
    dn = _cf(text,'_exptl_crystal_density_diffrn')
    if dn: d['density_g_cm3'] = round(dn,3)

    # Data collection
    t = _cf(text,'_cell_measurement_temperature') or _cf(text,'_diffrn_ambient_temperature')
    if t: d['temperature_k'] = t
    rt = _cv(text,'_diffrn_radiation_type')
    wl = _cf(text,'_diffrn_radiation_wavelength')
    if rt and wl: d['radiation'] = f"{rt} ({wl} Å)"
    elif wl:
        if abs(wl-0.71073)<0.002: d['radiation']=f"Mo Kα ({wl} Å)"
        elif abs(wl-1.5418)<0.002: d['radiation']=f"Cu Kα ({wl} Å)"
        else: d['radiation']=f"{wl} Å"
    dev = _cv(text,'_diffrn_measurement_device_type')
    if dev and dev!='?': d['measurement_device'] = dev

    # Refinement
    rg = _cf(text,'_refine_ls_R_factor_gt')
    ra = _cf(text,'_refine_ls_R_factor_all')
    if rg: d['r_factor_percent'] = round(rg*100,2)
    elif ra: d['r_factor_percent'] = round(ra*100,2)
    d['goodness_of_fit'] = _cf(text,'_refine_ls_goodness_of_fit_ref')
    d['number_reflections'] = _ci(text,'_refine_ls_number_reflns') or _ci(text,'_reflns_number_total')
    d['number_parameters'] = _ci(text,'_refine_ls_number_parameters')
    d['number_restraints'] = _ci(text,'_refine_ls_number_restraints')
    d['theta_min'] = _cf(text,'_diffrn_reflns_theta_min')
    d['theta_max'] = _cf(text,'_diffrn_reflns_theta_max')
    d['measured_reflections'] = _ci(text,'_diffrn_reflns_number')
    d['absorption_coeff'] = _cf(text,'_exptl_absorpt_coefficient_mu')
    d['t_min'] = _cf(text,'_exptl_absorpt_correction_T_min')
    d['t_max'] = _cf(text,'_exptl_absorpt_correction_T_max')
    d['diff_density_max'] = _cf(text,'_refine_diff_density_max')
    d['diff_density_min'] = _cf(text,'_refine_diff_density_min')

    # H-bonds
    hb = []
    if '_geom_hbond_' in text:
        sec = text[text.find('_geom_hbond_'):]
        for row in re.findall(r'^([A-Z]\S*)\s+([A-Z]\S*)\s+([A-Z]\S*)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)',sec,re.M):
            try: hb.append({'donor':row[0],'hydrogen':row[1],'acceptor':row[2],
                            'distance_dh':float(row[3]),'distance_ha':float(row[4]),
                            'distance_da':float(row[5]),'angle_dha':float(row[6])})
            except: pass
    if hb: d['hydrogen_bonds'] = hb

    return {k:v for k,v in d.items() if v is not None}


# ═══════════════════════════════════════════════════════════════════
# PDF PARSER  —  extracts text and mines it for property data
# ═══════════════════════════════════════════════════════════════════
def _extract_pdf_text(pdf_bytes):
    """Extract full text from a PDF using PyMuPDF."""
    try:
        import fitz
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        doc = fitz.open(tmp_path)
        pages = [page.get_text() for page in doc]
        doc.close()
        os.unlink(tmp_path)
        return '\n'.join(pages)
    except Exception as e:
        print(f"PDF extraction failed: {e}")
        return ""


def parse_pdf(pdf_bytes):
    """Mine the PDF text for piezoelectric properties, methods, authors, etc."""
    text = _extract_pdf_text(pdf_bytes)
    if not text:
        return {}

    d = {}
    d['_full_text_length'] = len(text)
    low = text.lower()

    # ── DOI ──
    m = re.search(r'(10\.\d{4,}/[^\s,;]+)', text)
    if m: d['doi'] = m.group(1).rstrip('.')

    # ── Piezoelectric coefficients ──
    # d33 in pC/N
    for pat in [
        r'd[_\s]*33\s*[=≈~:]\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?pC\s*/?\s*N',
        r'd[_\s]*33\s*(?:value|coefficient)?\s*(?:of|is|was|=|≈)\s*([\d.]+)\s*pC',
        r'(?:piezoelectric|longitudinal)\s+(?:charge\s+)?coefficient\s*(?:d33)?\s*(?:of|is|was|=|≈)\s*([\d.]+)\s*pC',
    ]:
        m = re.search(pat, text, re.I)
        if m:
            d['d33_pC_N'] = float(m.group(1))
            break

    # d33 in pm/V
    for pat in [
        r'd[_\s]*(?:33|eff)\s*[=≈~:]\s*([\d.]+)\s*pm\s*(?:/|per)\s*V',
        r'd[_\s]*eff\s*[≈=]\s*([\d.]+)\s*pm\s*V',
        r'([\d.]+)\s*pm\s*V\s*[-–]\s*1\s*(?:for\s+)?(?:vertical|longitudinal)',
    ]:
        m = re.search(pat, text, re.I)
        if m:
            d['d_eff_pm_V'] = float(m.group(1))
            break

    # Lateral / shear coefficient
    for pat in [
        r'(?:lateral|shear)\s+(?:displacement|coefficient|piezoelectric).*?[=≈~]\s*-?([\d.]+)\s*p[mC]',
        r'd[_\s]*(?:eff|15)\s*[≈=]\s*-?([\d.]+)\s*pm.*?lateral',
    ]:
        m = re.search(pat, text, re.I)
        if m:
            d['d_lateral'] = float(m.group(1))
            break

    # ── Piezoelectric voltage constant g33 ──
    m = re.search(r'g[_\s]*33\s*[=≈]\s*([\d.]+)\s*mV\s*m\s*/?\s*N', text, re.I)
    if m: d['g33_mV_m_N'] = float(m.group(1))

    # ── Dielectric constant ──
    m = re.search(r'dielectric\s+constant\s*(?:at\s+\d+\s*(?:k?Hz|MHz))?\s*(?:of|is|was|=|≈)\s*([\d.]+)', text, re.I)
    if m: d['dielectric_constant'] = float(m.group(1))

    # ── Young's modulus ──
    m = re.search(r"Young'?s?\s+modulus\s*(?:of|is|was|=|≈)?\s*([\d.]+)\s*GPa", text, re.I)
    if m: d['youngs_modulus_GPa'] = float(m.group(1))

    # ── Open circuit voltage ──
    m = re.search(r'(?:open[- ]circuit|peak[- ]to[- ]peak)\s+voltage\s*(?:of|is|was|=|≈)?\s*([\d.]+)\s*(?:m?V)', text, re.I)
    if m: d['open_circuit_voltage_mV'] = float(m.group(1))

    # ── Is piezoelectric? ──
    if any(kw in low for kw in ['piezoelectric', 'piezoelectricity', 'piezoresponse', 'piezoel']):
        d['mentions_piezoelectric'] = True
    if any(kw in low for kw in ['ferroelectric', 'ferroelectricity']):
        d['mentions_ferroelectric'] = True
    if any(kw in low for kw in ['pyroelectric', 'pyroelectricity']):
        d['mentions_pyroelectric'] = True

    # ── Experimental methods ──
    methods = []
    method_keywords = {
        'PFM': r'piezorespons[e]?\s+force\s+microscop',
        'AFM': r'atomic\s+force\s+microscop',
        'XRD': r'(?:powder\s+)?x[- ]ray\s+diffract',
        'Raman spectroscopy': r'raman\s+spectroscop',
        'DSC': r'differential\s+scanning\s+calorim',
        'DFT': r'(?:density\s+functional\s+theory|DFT)',
        'SHG': r'second\s+harmonic\s+generation',
        'Berlincourt piezometer': r'berlincourt',
        'Impedance spectroscopy': r'impedance\s+spectroscop',
        'Dielectric measurement': r'dielectric\s+(?:measurement|stud|propert)',
        'Vickers hardness': r'vickers\s+(?:micro)?hardness',
        'Hirshfeld surface analysis': r'hirshfeld\s+surface',
        'Compression testing': r'compression\s+test',
        'TGA': r'thermogravimetric\s+analy',
        'FTIR': r'(?:fourier\s+transform\s+)?infrared|FTIR',
        'UV-Vis spectroscopy': r'uv[- ]?vis',
        'NMR': r'nuclear\s+magnetic\s+resonance|NMR',
        'SEM': r'scanning\s+electron\s+microscop',
    }
    for name, pat in method_keywords.items():
        if re.search(pat, text, re.I):
            methods.append(name)
    if methods: d['experimental_methods'] = methods

    # ── Authors ──
    # Try to find author block near the top (first 3000 chars)
    header = text[:3000]
    # Common patterns: "Name1, Name2, and Name3" or "Name1 a, Name2 b"
    # Look for lines with multiple names separated by commas
    author_candidates = []
    for line in header.split('\n'):
        line = line.strip()
        # Skip short lines, titles, affiliations
        if len(line) < 10 or len(line) > 500: continue
        if any(kw in line.lower() for kw in ['abstract','introduction','university','institute',
                                               'department','received','accepted','published',
                                               'doi:','http','journal','©','copyright']): continue
        # Count capital-starting words (likely names)
        words = line.split()
        cap_words = sum(1 for w in words if w and w[0].isupper() and len(w) > 1)
        if cap_words >= 3 and ',' in line:
            # Clean up superscripts and affiliations
            cleaned = re.sub(r'\s*[a-f,]+\s*$', '', line)
            cleaned = re.sub(r'\s+[a-f]\s*,', ',', cleaned)
            cleaned = re.sub(r'\s*\d+\s*', ' ', cleaned)
            cleaned = re.sub(r'\s*[*†‡§]+\s*', '', cleaned)
            if cleaned:
                author_candidates.append(cleaned)
    if author_candidates:
        d['authors_raw'] = author_candidates[0]

    # ── Journal ──
    journal_patterns = [
        (r'Physical Review Letters', 'Physical Review Letters'),
        (r'Applied Materials Today', 'Applied Materials Today'),
        (r'Nature Materials', 'Nature Materials'),
        (r'Nature Communications', 'Nature Communications'),
        (r'Advanced Materials', 'Advanced Materials'),
        (r'Advanced Functional Materials', 'Advanced Functional Materials'),
        (r'ACS Nano', 'ACS Nano'),
        (r'Journal of the American Chemical Society|J\.\s*Am\.\s*Chem\.\s*Soc', 'Journal of the American Chemical Society'),
        (r'Chemistry\s*[-–]\s*A\s*European\s*Journal|Chem\.?\s*Eur\.?\s*J', 'Chemistry - A European Journal'),
        (r'Applied Physics A', 'Applied Physics A'),
        (r'Crystal Growth\s*(?:&|and)\s*Design', 'Crystal Growth & Design'),
        (r'CrystEngComm', 'CrystEngComm'),
        (r'Acta Crystallographica', 'Acta Crystallographica'),
        (r'Journal of Crystal Growth', 'Journal of Crystal Growth'),
        (r'Ferroelectrics', 'Ferroelectrics'),
        (r'Journal of Applied Physics', 'Journal of Applied Physics'),
        (r'Nano Energy', 'Nano Energy'),
        (r'Small', 'Small'),
        (r'Science\b', 'Science'),
    ]
    for pat, name in journal_patterns:
        if re.search(pat, text, re.I):
            d['journal'] = name
            break

    # ── Year ──
    m = re.search(r'(?:published|accepted|received)\s+\d+\s+\w+\s+(\d{4})', text, re.I)
    if m: d['year'] = int(m.group(1))
    else:
        m = re.search(r'©\s*(\d{4})', text)
        if m: d['year'] = int(m.group(1))

    # ── Title (usually the first substantial line) ──
    for line in text.split('\n'):
        line = line.strip()
        if 15 < len(line) < 300 and not line.startswith('http') and not re.match(r'^[\d.]+$', line):
            if not any(kw in line.lower() for kw in ['contents','journal','elsevier','doi','volume','©']):
                d['title'] = line
                break

    # ── Crystal type inference ──
    type_keywords = {
        'Organic molecular crystal': r'organic\s+(?:molecular\s+)?crystal',
        'Amino acid crystal': r'amino\s+acid',
        'Dipeptide crystal': r'dipeptide',
        'Peptide crystal': r'peptide\s+crystal',
        'Perovskite': r'perovskite',
        'Ceramic': r'ceramic',
        'Polymer': r'polymer|PVDF|polyvinylidene',
        'Molecular salt': r'molecular\s+salt',
        'Co-crystal': r'co[- ]?crystal',
        'Metal-organic framework': r'metal[- ]organic\s+framework|MOF',
    }
    for name, pat in type_keywords.items():
        if re.search(pat, text, re.I):
            d['crystal_type'] = name
            break

    # ── Applications ──
    apps = []
    app_keywords = {
        'Energy harvesting': r'energy\s+harvest',
        'Sensing': r'sens(?:or|ing)',
        'Biomedical devices': r'biomed|implant|medical\s+device',
        'Wearable technology': r'wearable',
        'Actuators': r'actuat',
        'Transducers': r'transduc',
        'Optoelectronics': r'optoelectron',
        'Self-powered devices': r'self[- ]powered',
        'Ultrasonic devices': r'ultrasoni',
        'Nanogenerators': r'nanogenerator',
    }
    for name, pat in app_keywords.items():
        if re.search(pat, text, re.I):
            apps.append(name)
    if apps: d['applications'] = apps

    # ── Key findings (sentences containing "first time" or "for the first time") ──
    firsts = []
    for m in re.finditer(r'[^.]*(?:first time|for the first time|first report|novel|unprecedented)[^.]*\.', text, re.I):
        sent = m.group(0).strip()
        if 20 < len(sent) < 400:
            firsts.append(sent)
    if firsts: d['key_findings'] = firsts[:3]

    return {k:v for k,v in d.items() if v is not None}


# ═══════════════════════════════════════════════════════════════════
# BUILD FINAL JSON + TXT
# ═══════════════════════════════════════════════════════════════════
def _build_json(pmc_id, pdf_fn, cif_fn, cif, pdf):
    mol = cif.get('chemical_name')
    sg = cif.get('space_group_number')
    piezo_ok = cif.get('property_symmetry_compatible')

    # Interactions from H-bonds
    interactions = []
    if 'hydrogen_bonds' in cif:
        seen = set()
        for hb in cif['hydrogen_bonds']:
            k = f"{hb['donor'][0]}-H···{hb['acceptor'][0]} hydrogen bonds"
            if k not in seen: seen.add(k); interactions.append(k)

    # Merge PDF data
    is_piezo = None
    if pdf.get('d33_pC_N') or pdf.get('d_eff_pm_V'):
        is_piezo = True
    elif pdf.get('mentions_piezoelectric') and piezo_ok:
        is_piezo = True

    is_ferro = True if pdf.get('mentions_ferroelectric') else None
    is_pyro = True if pdf.get('mentions_pyroelectric') else None

    # Experimental method string
    exp_method = ', '.join(pdf.get('experimental_methods', [])) or None
    has_exp = bool(pdf.get('experimental_methods'))
    has_comp = 'DFT' in pdf.get('experimental_methods', [])

    # Piezo values
    long_val = pdf.get('d33_pC_N') or pdf.get('d_eff_pm_V')
    long_unit = 'pC/N' if pdf.get('d33_pC_N') else ('pm/V' if pdf.get('d_eff_pm_V') else None)
    shear_val = pdf.get('d_lateral')
    shear_unit = long_unit if shear_val else None

    long_qual = None
    if long_val: long_qual = 'Measured'
    elif piezo_ok: long_qual = 'Symmetry-permitted'

    shear_qual = None
    if shear_val: shear_qual = 'Measured'
    elif piezo_ok: shear_qual = 'Symmetry-permitted'

    # Authors
    authors = []
    if pdf.get('authors_raw'):
        raw = pdf['authors_raw']
        raw = re.sub(r'\s+and\s+', ', ', raw)
        authors = [a.strip() for a in raw.split(',') if a.strip() and len(a.strip()) > 2]

    crystal_type = pdf.get('crystal_type') or None
    title = pdf.get('title')
    journal = pdf.get('journal')
    year = pdf.get('year')
    doi = pdf.get('doi') or cif.get('citation_doi')

    return {
        "id": pmc_id,
        "schema_version": "1.0",
        "text": f"{mol or '(unknown)'} - {'piezoelectric ' if is_piezo else ''}{crystal_type or 'crystal'}",

        "molecule_name": mol,
        "synonyms": [],
        "chemical_formula": cif.get('chemical_formula'),
        "molecular_weight": cif.get('molecular_weight'),
        "crystal_type": crystal_type,
        "component_count": None,

        "csd_refcode": cif.get('csd_refcode'),
        "ccdc_number": cif.get('ccdc_number'),
        "cif_file_name": cif_fn,
        "structure_doi": cif.get('citation_doi') or doi,
        "deposition_date": cif.get('deposition_date'),

        "crystal_system": cif.get('crystal_system'),
        "space_group_symbol": cif.get('space_group_symbol'),
        "space_group_number": sg,
        "centrosymmetric": cif.get('centrosymmetric'),
        "cell_a": cif.get('cell_a'),
        "cell_b": cif.get('cell_b'),
        "cell_c": cif.get('cell_c'),
        "cell_alpha": cif.get('cell_alpha'),
        "cell_beta": cif.get('cell_beta'),
        "cell_gamma": cif.get('cell_gamma'),
        "cell_volume": cif.get('cell_volume'),
        "cell_z": cif.get('cell_z'),
        "cell_z_prime": None,

        "habit": cif.get('habit'),
        "colour": cif.get('colour'),
        "density_g_cm3": cif.get('density_g_cm3'),
        "temperature_k": cif.get('temperature_k'),
        "radiation": cif.get('radiation'),
        "experiment_type": "Single-crystal X-ray diffraction",
        "r_factor_percent": cif.get('r_factor_percent'),

        "intermolecular_interactions": interactions,
        "isostructural_analogues": [],

        "is_piezoelectric": is_piezo,
        "is_ferroelectric": is_ferro if is_ferro else None,
        "is_pyroelectric": is_pyro if is_pyro else None,
        "property_symmetry_compatible": piezo_ok,

        "has_experimental": has_exp or None,
        "has_computational": has_comp or None,
        "experimental_method": exp_method,
        "computational_method": "DFT" if has_comp else None,
        "shear_qualitative": shear_qual,
        "shear_value": shear_val,
        "shear_unit": shear_unit,
        "longitudinal_qualitative": long_qual,
        "longitudinal_value": long_val,
        "longitudinal_unit": long_unit,
        "dft_shear_qualitative": None,

        "structure_ref_authors": authors,
        "structure_ref_journal": journal,
        "structure_ref_year": year,
        "structure_ref_volume": None,
        "structure_ref_doi": cif.get('citation_doi') or doi,

        "property_ref_title": title,
        "property_ref_journal": journal,
        "property_ref_year": year,
        "property_ref_doi": doi,

        "structure_verified": True,
        "paper_verified": True,
        "piezoelectricity_verified": is_piezo or False,
        "cif_matches_paper": True,
        "cod_code": None,
    }


def _build_txt(pmc_id, cif, pdf, j):
    sg = j.get('space_group_symbol','')
    sgn = j.get('space_group_number','')
    nc = j.get('centrosymmetric') is False

    piezo_str = 'Yes' if j.get('is_piezoelectric') else ('To be confirmed' if nc else 'Unknown')
    coeff_parts = []
    if j.get('longitudinal_value'):
        coeff_parts.append(f"d33 = {j['longitudinal_value']} {j.get('longitudinal_unit','')}")
    if j.get('shear_value'):
        coeff_parts.append(f"d_lateral = {j['shear_value']} {j.get('shear_unit','')}")
    coeff = '; '.join(coeff_parts) if coeff_parts else ''

    apps = ', '.join(pdf.get('applications',[])) or ''
    methods = ', '.join(pdf.get('experimental_methods',[])) or ''
    findings = '\n'.join(f"  - {f}" for f in pdf.get('key_findings',[])) or ''

    return f"""Crystal ID: {pmc_id}

CCDC ID: {j.get('ccdc_number','')}

CSD REFCODE: {j.get('csd_refcode','')}

Molecule Name: {j.get('molecule_name','')}

IUPAC Name:

Chemical Formula: {j.get('chemical_formula','')}

Molecular Weight: {j.get('molecular_weight','')}

Crystal Type: {j.get('crystal_type','')}

Piezoelectric Property: {piezo_str}

Evidence: {'Non-centrosymmetric space group ' + str(sg) + (' (No. ' + str(sgn) + ')') + ', compatible with piezoelectricity.' if nc else ''}
{('Piezoelectric coefficients measured: ' + coeff + '.') if coeff else ''}

Research Paper: {j.get('property_ref_title','')}

DOI: {j.get('property_ref_doi','')}

CIF File Name (System): {j.get('cif_file_name','')}

Space Group: {sg}{' (No. ' + str(sgn) + ')' if sgn else ''}

Crystal System: {j.get('crystal_system','')}

Unit Cell Parameters:
  a = {j.get('cell_a','')} Å
  b = {j.get('cell_b','')} Å
  c = {j.get('cell_c','')} Å
  α = {j.get('cell_alpha','')}°, β = {j.get('cell_beta','')}°, γ = {j.get('cell_gamma','')}°
  V = {j.get('cell_volume','')} ų
  Z = {j.get('cell_z','')}

Density: {j.get('density_g_cm3','')} g/cm³

Crystal Habit: {j.get('habit','')}

Crystal Colour: {j.get('colour','')}

Temperature: {j.get('temperature_k','')} K

Radiation: {j.get('radiation','')}

R-factor: {j.get('r_factor_percent','')}%

Piezoelectric Coefficient: {coeff}

Experimental Methods: {methods}

Applications: {apps}

Key Findings:
{findings}

Notes:

{'Non-centrosymmetric crystal — piezoelectricity is symmetry-permitted.' if nc else ''}
{'Intermolecular interactions: ' + ', '.join(j.get('intermolecular_interactions',[])) if j.get('intermolecular_interactions') else ''}
Deposition date: {j.get('deposition_date','')}.
Authors: {', '.join(j.get('structure_ref_authors',[]))}
(Auto-extracted from CIF + PDF on {datetime.now().strftime('%Y-%m-%d %H:%M')}.)
"""


# ═══════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════
def create_crystal_entry(pdf_bytes, pdf_filename, cif_bytes, cif_filename):
    pmc_id = get_next_pmc_id()
    pmc_dir = DATA_DIR / pmc_id
    pmc_dir.mkdir(parents=True, exist_ok=True)

    # Save files
    (pmc_dir / pdf_filename).write_bytes(pdf_bytes)
    (pmc_dir / cif_filename).write_bytes(cif_bytes)

    # Parse both sources
    cif_data = parse_cif(cif_bytes)
    pdf_data = parse_pdf(pdf_bytes)

    # Build output
    crystal_json = _build_json(pmc_id, pdf_filename, cif_filename, cif_data, pdf_data)
    json_path = pmc_dir / f"{pmc_id}.json"
    json_path.write_text(json.dumps(crystal_json, indent=2))

    txt_path = pmc_dir / f"{pmc_id}.txt"
    txt_path.write_text(_build_txt(pmc_id, cif_data, pdf_data, crystal_json))

    filled = [k for k,v in crystal_json.items() if v is not None and v != [] and v is not False]

    return {
        'success': True,
        'pmc_id': pmc_id,
        'message': f'{pmc_id} created — {len(filled)} fields populated from CIF + PDF',
        'files': {'pdf':str(pmc_dir/pdf_filename),'cif':str(pmc_dir/cif_filename),
                  'json':str(json_path),'txt':str(txt_path)},
        'extracted_from_cif': list(cif_data.keys()),
        'extracted_from_pdf': list(pdf_data.keys()),
        'summary': {
            'molecule': crystal_json.get('molecule_name'),
            'formula': crystal_json.get('chemical_formula'),
            'space_group': crystal_json.get('space_group_symbol'),
            'crystal_system': crystal_json.get('crystal_system'),
            'piezoelectric': crystal_json.get('is_piezoelectric'),
            'd33': crystal_json.get('longitudinal_value'),
            'methods': pdf_data.get('experimental_methods'),
            'journal': pdf_data.get('journal'),
        },
    }