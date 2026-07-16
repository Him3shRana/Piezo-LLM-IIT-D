# LAMMPS COMMAND

 cd ~/himesh_work/MACE-LAMMPS
python run_nvt_lammps.py \
    --pmc PMC-001 \
    --temps 300 \
    --model medium \
    --supercell 2 \
    --eq-ps 1 \
    --prod-ps 2 \
    --restart-every 100

# Copy Data FRom GPU to Local Machine
 scp -r cyz218376@pragya.iitd.ac.in:/home/chemistry/phd/cyz218376/himesh_work/MACE-LAMMPS/PMC-001/NVT_results /home/pravega2/Documents
/Piezo-LLM/simulations/LAMMPS-Simulations/

# LAMMPS rdf_comparison run Command to plot pairwise and Total Graph
python3 rdf_compare.py PMC-001 --temp 300 --engine lammps

