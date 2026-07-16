# Activate the Environment (mace-gpu) will be used for all LAMMPS Simulations
source /home/chemistry/phd/cyz218376/home/software/mace-lammps-plumed/env.sh


# To run simulation using mace-off-23 (medium version) using lammps for nvt (--fresh means start from beginning and not passing it will continue from where it has left 
# you must be in ~/himesh_work/testing
python3 all_nvt_lammps.py --pmc PMC-001 --model mace-off23 --version medium --temperature 300 \
  --minimize-steps 200 --equil-step 2000 --target-step 20000 --gpu --fresh --confirm-fresh
# Trajectory will be saved for rdf graph plot at (Trajectory for RDF: runs/PMC-001/lammps-nvt/mace-off23-medium/300K_2x2x2/production/traj.extxyz)













#To run simulation on lammps engine for npt
# Need Environment Given at the Top

python3 all_npt_lammps.py --pmc PMC-001 --model mace-off23 --version medium --temperature 300 --pressure 1.0 \
  --minimize-steps 200 --equil-step 2000 --target-step 5000 --gpu --fresh --confirm-fresh

# To get the Graph USed the below command (it Just need the extxyz file for Graph plotting   ----- Also stores the resylt in that folder)
$ python3 all_rdf_compare.py --run-dir runs/PMC-001/lammps-npt/mace-off23-medium/300K_1bar_2x2x2

#Results Fetching from lammps NPT
rsync -avz --progress \
  cyz218376@pragya.iitd.ac.in:~/himesh_work/testing/runs/PMC-001/lammps-npt/ \
  /home/pravega2/Documents/Piezo-LLM/simulations/lammps-simulations/lammps-npt/PMC-001/



