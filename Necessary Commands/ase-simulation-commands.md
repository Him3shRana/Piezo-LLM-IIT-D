##MACE-Polar Running using ASE Engine /start
#Small Model 
#Activate Environment
source /home/chemistry/phd/cyz218376/home/software/mace-polar-env/bin/activate
#Location and environment needed to run
(mace-polar-env) (base) [cyz218376@amilan002 ~/himesh_work/ASE-Simulations/MACE-polar/SMALL-model]

#run simulation on small model
$ python3 run_nvt.py PMC-001   --temps 300   --eq-steps 500   --steps 3000   --model /home/chemistry/phd/cyz218376/himesh_work/mace_models/MACE-POLAR-1-S.model

#Command to copy Results into local MAchine
scp -r cyz218376@pragya.iitd.ac.in:~/himesh_work/ASE-Simulations/MACE-polar/SMALL-model/simulations/PMC-001 \
//home/pravega2/Documents/Piezo-LLM/simulations/asc-simulations
#end


#Running NPT Simulation Using ASE for mace-off-23 /start
(base) [cyz218376@amilan012 ~/himesh_work/ASE-Simulations/npt/mace-off-23]
$ python3 run_npt.py \
PMC-001 \
--temps 300 \
--eq-steps 20000 \
--npt-eq-steps 200000 \
--npt-steps 2000000 \
--pressure 1 \
--model small
#For tuning the NPT simulation change values at top of md_common ttime and ptime (large value -> more flexible ,small value -> more rigid and unequal Graph) 

#if you have done very large simulation like 20 lakhs then put stride =10 like   
python3 rdf_compare.py PMC-001 --ensemble npt --temp 300 --engine mace-ase --model small --stride 10
                (To plot the rdf between every pair) As Very Large simulation will take every frame (20,0000 frames abd doin so will be very memory and Time Taking)




