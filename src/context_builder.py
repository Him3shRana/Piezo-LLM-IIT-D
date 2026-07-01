"""
=============================================================
Piezo-LLM
Context Builder

Purpose
-------
The retriever returns one or more crystal JSON files.

This module converts those raw JSON files into a clean,
well-structured scientific context for the LLM.

Responsibilities
----------------
1. Read retrieved crystal JSON(s)
2. Ignore missing/empty information
3. Organize information into logical sections
4. Produce a readable scientific context

This module DOES NOT communicate with the LLM.
It only prepares the knowledge.
=============================================================
"""


class ContextBuilder:

    def __init__(self):
        """
        Nothing to initialize for now.

        Future possibilities:
        - Token counting
        - Context length limits
        - Query-aware context selection
        """
        pass

    # ==========================================================
    # Helper Functions
    # ==========================================================

    def value(self, data, key):
        """
        Safely retrieve a value from JSON.

        Returns None if the field is missing.
        """

        value = data.get(key)

        if value is None:
            return None

        if value == "":
            return None

        if isinstance(value, list):

            if len(value) == 0:
                return None

            return ", ".join(str(v) for v in value)

        return value

    # ----------------------------------------------------------

    def add_field(self, context, label, value):
        """
        Add a field only if it contains useful information.

        This keeps the context short and avoids lines like:

        Formula : Not Available
        """

        if value is None:
            return

        context.append(f"{label} : {value}")

    # ----------------------------------------------------------

    def add_heading(self, context, title):
        """
        Adds a nicely formatted section heading.
        """

        context.append("")
        context.append("=" * 60)
        context.append(title)
        context.append("=" * 60)

    # ==========================================================
    # Build Context for ONE Crystal
    # ==========================================================

    def build_single_context(self, crystal):

        context = []

        # ------------------------------------------------------
        # Basic Information
        # ------------------------------------------------------

        self.add_heading(context, "BASIC INFORMATION")

        self.add_field(
            context,
            "Crystal ID",
            self.value(crystal, "id")
        )

        self.add_field(
            context,
            "Molecule",
            self.value(crystal, "molecule_name")
        )

        self.add_field(
            context,
            "Synonyms",
            self.value(crystal, "synonyms")
        )

        self.add_field(
            context,
            "Chemical Formula",
            self.value(crystal, "chemical_formula")
        )

        self.add_field(
            context,
            "Molecular Weight",
            self.value(crystal, "molecular_weight")
        )

        self.add_field(
            context,
            "Crystal Type",
            self.value(crystal, "crystal_type")
        )

        self.add_field(
            context,
            "Components",
            self.value(crystal, "component_count")
        )

        # ------------------------------------------------------
        # Crystal Structure
        # ------------------------------------------------------

        self.add_heading(context, "CRYSTAL STRUCTURE")

        self.add_field(
            context,
            "Crystal System",
            self.value(crystal, "crystal_system")
        )

        self.add_field(
            context,
            "Space Group",
            self.value(crystal, "space_group_symbol")
        )

        self.add_field(
            context,
            "Space Group Number",
            self.value(crystal, "space_group_number")
        )

        self.add_field(
            context,
            "Centrosymmetric",
            self.value(crystal, "centrosymmetric")
        )

        self.add_field(
            context,
            "CSD Refcode",
            self.value(crystal, "csd_refcode")
        )

        self.add_field(
            context,
            "CCDC Number",
            self.value(crystal, "ccdc_number")
        )

        # ------------------------------------------------------
        # Unit Cell
        # ------------------------------------------------------

        self.add_heading(context, "UNIT CELL")

        self.add_field(context, "a (Å)", self.value(crystal, "cell_a"))
        self.add_field(context, "b (Å)", self.value(crystal, "cell_b"))
        self.add_field(context, "c (Å)", self.value(crystal, "cell_c"))

        self.add_field(context, "α", self.value(crystal, "cell_alpha"))
        self.add_field(context, "β", self.value(crystal, "cell_beta"))
        self.add_field(context, "γ", self.value(crystal, "cell_gamma"))

        self.add_field(context, "Volume", self.value(crystal, "cell_volume"))
        self.add_field(context, "Z", self.value(crystal, "cell_z"))

        # ------------------------------------------------------
        # Piezoelectric Properties
        # ------------------------------------------------------

        self.add_heading(context, "PIEZOELECTRIC PROPERTIES")

        self.add_field(
            context,
            "Piezoelectric",
            self.value(crystal, "is_piezoelectric")
        )

        self.add_field(
            context,
            "Ferroelectric",
            self.value(crystal, "is_ferroelectric")
        )

        self.add_field(
            context,
            "Pyroelectric",
            self.value(crystal, "is_pyroelectric")
        )

        self.add_field(
            context,
            "Symmetry Compatible",
            self.value(crystal, "property_symmetry_compatible")
        )

        self.add_field(
            context,
            "Experimental Method",
            self.value(crystal, "experimental_method")
        )

        self.add_field(
            context,
            "Computational Method",
            self.value(crystal, "computational_method")
        )

        self.add_field(
            context,
            "Longitudinal Value",
            self.value(crystal, "longitudinal_value")
        )

        self.add_field(
            context,
            "Longitudinal Unit",
            self.value(crystal, "longitudinal_unit")
        )

        self.add_field(
            context,
            "Shear Value",
            self.value(crystal, "shear_value")
        )

        self.add_field(
            context,
            "Shear Unit",
            self.value(crystal, "shear_unit")
        )

        # ------------------------------------------------------
        # Experimental Information
        # ------------------------------------------------------

        self.add_heading(context, "EXPERIMENTAL INFORMATION")

        self.add_field(
            context,
            "Temperature (K)",
            self.value(crystal, "temperature_k")
        )

        self.add_field(
            context,
            "Density (g/cm³)",
            self.value(crystal, "density_g_cm3")
        )

        self.add_field(
            context,
            "Experiment",
            self.value(crystal, "experiment_type")
        )

        self.add_field(
            context,
            "Radiation",
            self.value(crystal, "radiation")
        )

        self.add_field(
            context,
            "R Factor (%)",
            self.value(crystal, "r_factor_percent")
        )

        # ------------------------------------------------------
        # References
        # ------------------------------------------------------

        self.add_heading(context, "REFERENCES")

        self.add_field(
            context,
            "Property DOI",
            self.value(crystal, "property_ref_doi")
        )

        self.add_field(
            context,
            "Structure DOI",
            self.value(crystal, "structure_ref_doi")
        )

        self.add_field(
            context,
            "Property Journal",
            self.value(crystal, "property_ref_journal")
        )

        self.add_field(
            context,
            "Structure Journal",
            self.value(crystal, "structure_ref_journal")
        )

        # ------------------------------------------------------
        # Scientific Description
        # ------------------------------------------------------

        self.add_heading(context, "SCIENTIFIC DESCRIPTION")

        description = self.value(crystal, "text")

        if description is not None:
            context.append(description)

        return "\n".join(context)

    # ==========================================================
    # Build Context for Multiple Crystals
    # ==========================================================

    def build_context(self, retrieved_results):
        """
        Convert one or more retrieved crystal JSONs into
        a single context string.
        """

        if not retrieved_results:
            return "No relevant crystal information found."

        contexts = []

        for result in retrieved_results:

            crystal = result["json"]

            contexts.append(
                self.build_single_context(crystal)
            )

            contexts.append("\n" + "#" * 80 + "\n")

        return "\n".join(contexts)


# ==============================================================
# Testing
# ==============================================================

if __name__ == "__main__":

    from json_retriever import JSONRetriever

    retriever = JSONRetriever()

    results = retriever.retrieve("meta nitroaniline")

    builder = ContextBuilder()

    context = builder.build_context(results)

    print(context)