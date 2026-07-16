# To run Simulation... 1stly Access the GPU and  Set the environment using
source /home/chemistry/phd/cyz218376/home/software/mace-lammps-plumed/env.sh

#ase-nvt
# Then to run simulation (default model medium)
python3 all_nvt_ase.py --pmc PMC-001 --model mace-off23 --version medium --temperature 300 --equil-step 2000 --target-step 5000 --gpu

#After the Simulation is Done.... Plot the graph using
python3 all_rdf_compare.py --run-dir runs/PMC-001/ase-nvt/mace-off23-medium/300K_2x2x2

#After the Graph plotting Extract whole of the outputs into the Local Machines Using below Command
rsync -avz --progress \
  cyz218376@pragya.iitd.ac.in:~/himesh_work/testing/runs/PMC-001/ase-nvt/ \
  /home/pravega2/Documents/Piezo-LLM/simulations/ase-simulations/ase-nvt/PMC-001/


#ase-npt (Set The Above Environment 1st)  mace-off23 ---------------
#Then run Simulation (Default model Medium)

python3 all_npt_ase.py --pmc PMC-001 --model mace-off23 --version medium --temperature 300 --pressure 1.0 \
  --equil-step 2000 --target-step 5000 --gpu --fresh --confirm-fresh

#After The Simulation is Done--- Plot The graph using 
python3 all_rdf_compare.py --run-dir runs/PMC-001/ase-npt/mace-off23-medium/300K_1bar_2x2x2

#Then After Graph Plotting.... Save the Results into The Local MAchine Using below Command--- Note : Run the Command in  your Local Machine
rsync -avz --progress \
  cyz218376@pragya.iitd.ac.in:~/himesh_work/testing/runs/PMC-001/ase-npt/ \
  /home/pravega2/Documents/Piezo-LLM/simulations/ase-simulations/ase-npt/PMC-001/
  
#More (Extra Commands Used)
 python3 all_npt_ase.py --pmc PMC-001 --model polarmace --version small --temperature 300 --pressure 1.0   --equil-step 20000 --target-step 2000000 --gpu
 
 
#-----------------------------To use mace-mp0 model--------------------------------------------------
Environment ----->  source /home/chemistry/phd/cyz218376/home/software/mace-lammps-plumed/env.sh

Command -----> python all_npt_ase.py --pmc PMC-001 --model mace-mp0 --version medium --temperature 300 --pressure 1.0 --equil-step 20000 --target-step 200000 --gpu
 
 
 
#-------------------------To use CHGNet MOdel------------------------------
Environment --->>  source /home/chemistry/phd/cyz218376/home/software/chgnet_env/bin/activate

Command ---> python all_npt_ase.py --pmc PMC-001 --model chgnet --version pretrained --temperature 300 --pressure 1.0 --equil-step 20000 --target-step 200000 --gpu


#----------------------------To Use Grace-----------------------------------------------------
Environment ----> source /home/chemistry/phd/cyz218376/home/software/grace_env/bin/activate

Command -----> python all_npt_ase.py --pmc PMC-001 --model grace --version GRACE-2L-OMAT-medium-ft-AM --temperature 300 --pressure 1.0 --equil-step 20000 --target-step 200000

Grace another Model Command ----> python all_npt_ase.py --pmc PMC-001 --model grace --version GRACE-2L-OAM --temperature 300 --pressure 1.0 --equil-step 20000 --target-step 200000



