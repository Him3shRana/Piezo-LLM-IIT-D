// Crystal model

export interface Crystal {

  pmc_id: string;

  schema_version: string;

  text: string;

  molecule_name: string;

  synonyms: string[];

  chemical_formula: string;

  molecular_weight: number | null;

  crystal_type: string;

  component_count: number;

  csd_refcode: string | null;

  ccdc_number: number | null;

  cif_file_name: string | null;

  structure_doi: string | null;

  deposition_date: string | null;

  crystal_system: string;

  space_group_symbol: string;

  space_group_number: number;

  centrosymmetric: boolean;

  cell_a: number | null;

  cell_b: number | null;

  cell_c: number | null;

  cell_alpha: number | null;

  cell_beta: number | null;

  cell_gamma: number | null;

  cell_volume: number | null;

  cell_z: number | null;

  cell_z_prime: number | null;

  habit: string | null;

  colour: string | null;

  density_g_cm3: number | null;

  temperature_k: number | null;

  radiation: string | null;

  experiment_type: string | null;

  r_factor_percent: number | null;

  cod_code: string | null;

  intermolecular_interactions: string[];

  isostructural_analogues: string[];

  is_piezoelectric: boolean;

  is_ferroelectric: boolean | null;

  is_pyroelectric: boolean | null;

  property_symmetry_compatible: boolean;

  property_ref_doi: string | null;

}