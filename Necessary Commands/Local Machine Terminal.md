# Step 1: Sync data TO GPU server (only when you add new crystals)
rsync -avz ~/Documents/Piezo-LLM/data/ cyz218376@pragya.iitd.ac.in:~/himesh_work/data/

# Step 2: Copy results FROM GPU server (after simulation finishes)
scp -r cyz218376@pragya.iitd.ac.in:~/himesh_work/simulations/PMC-XXX/ ~/Documents/Piezo-LLM/simulations/PMC-XXX/

# Step 3: Run analysis (generates graphs)
cd ~/Documents/Piezo-LLM/src
python3 analyse_simulation.py

# Step 4: View graphs
xdg-open ~/Documents/Piezo-LLM/simulations/PMC-XXX/analysis/comparison_with_experiment.png

# Step 5: Start the GUI
python3 backend.py &
cd ../gui && npm run dev

# Step 6: Open browser
# http://localhost:5173


# Copying RDF Compare results from GPU to Local Machine
 scp -r cyz218376@pragya.iitd.ac.in:/home/chemistry/phd/cyz218376/himesh_work/MACE-off-23/SMALL-model/simulations/PMC-001/NVT_results/03_nvt_production/300K/rdf_compare ~/Documents/Piezo-LLM/simulations/MACE-off-23-Simulations
