# Step 1: SSH into server
ssh -X cyz218376@pragya.iitd.ac.in

# Step 2: Get a GPU node (if needed)
# (depends on your HPC — you might already be on amilan002)

# Step 3: Go to project folder
cd ~/himesh_work

# Step 4: Set environment
export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1

# Step 5: Run simulation (change PMC-XXX and options as needed)
python3 run_all.py PMC-001 --temps 300 --timestep 0.5 \
  --eq-steps 20000 --steps 200000 \
  --npt-eq-steps 40000 --npt-steps 200000 \
  --model medium --pressure 1.0
# Examples:
python3 run_all.py PMC-007 --temps 300                    # L-Alanine at 300K
python3 run_all.py PMC-010 --temps 100 200 300 400        # 4 temperatures
python3 run_all.py PMC-022 --temps 300 --size 3            # 3x3x3 supercell
python3 run_all.py PMC-007 --temps 300 --steps 10000       # longer simulation
python3 run_all.py all --temps 300                         # ALL molecules
python3 run_all.py --list                                  # see available molecules

# Step 6: When done, check results
ls simulations/PMC-XXX/md_results/
cat simulations/PMC-XXX/md_results/300K/thermo_300K.csv | head -5


# Gpu Util Check
watch -n 1 "nvidia-smi -i 5"

#After Running of nvt and npt

# rdf_analysis.py 
python3 rdf_analysis.py simulations/PMC-004/NVT_results/03_nvt_production/300K/production-trajectory.pdb
python3 rdf_analysis.py simulations/PMC-004/NPT_results/04_npt_production/300K/trajectory.pdb

#rdf_compare
# NVT production RDF comparison
python3 rdf_compare.py PMC-004 --temp 300 --ensemble nvt

# NPT production RDF comparison
python3 rdf_compare.py PMC-004 --temp 300 --ensemble npt
