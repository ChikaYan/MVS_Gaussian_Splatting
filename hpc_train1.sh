#!/bin/bash
#SBATCH --account OZTIRELI-SL2-GPU
#SBATCH -p ampere
#SBATCH --nodes 1
#SBATCH --gres=gpu:1
#SBATCH --time=15:00:00
#SBATCH --mail-type=NONE

. /etc/profile.d/modules.sh
module unload cuda/8.0
module unload rhel8/default-gpu
module unload cuda/11.4
module unload ucx/1.11.1/gcc-9.4.0-lktqyl4
module unload cuda/11.4.0/gcc-9.4.0-3hnxhjt
module load cuda/11.8
module load cudnn/8.9_cuda-11.8

module unload gcc-5.4.0-gcc-4.8.5-fis24gg
module load gcc-7.2.0-gcc-4.8.5-pqn7o2k
source /usr/local/software/archive/linux-scientific7-x86_64/gcc-9/miniconda3-4.7.12.1-rmuek6r3f6p3v6fdj7o2klyzta3qhslh/etc/profile.d/conda.sh
conda activate mvsnerf
#! module purge
#! module load rhel8/default-amp
#! module load cuda/11.1 cudnn/8.0_cuda-11.1
#! source /usr/local/software/archive/linux-scientific7-x86_64/gcc-9/miniconda3-4.7.12.1-rmuek6r3f6p3v6fdj7o2klyzta3qhslh/etc/profile.d/conda.sh
#! conda activate nex
#! python train_gs_mvs_nerf_finetuning_pl.py --dataset_name dtu_ft_gs --datadir /rds/user/hl589/hpc-work/data/dtu_example/scan114 --expname scan114_gs-mvsnerf-ft-vo0.00005-model0.0001-op0.05-scale0.01-ds0.01 --model_lr 0.0001 --volume_lr 0.00005 --with_rgb_loss  --batch_size 1 --num_epochs 60000  --imgScale_test 1.0   --pad 24 --ckpt ./ckpts/mvsnerf-v0.tar --N_vis 10 --net_type v3 --netchunk 100000
#! python sanity_check.py --dataset_name dtu_ft_gs --datadir /rds/user/hl589/hpc-work/data/dtu_example/scan114 --expname checkgs-0.0005 --with_rgb_loss  --batch_size 1 --num_epochs 300000  --imgScale_test 1.0   --pad 24 --ckpt ./ckpts/mvsnerf-v0.tar --N_vis 10 --net_type v3 --netchunk 100000

#python train_gs_mvs_nerf_finetuning_pl.py --dataset_name dtu_ft_gs --datadir /rds/user/hl589/hpc-work/data/dtu_example/scan114 --savedir /rds/project/rds-JDeuXlFW9KE/hanxue_project/mvsnerf_exp --expname singleimage_nopointloss_multi_volume_scan114_gs-mvsnerf-ft-lr1e-4 --num_epochs 60000  --multi_volume --lrate 0.0001  --imgScale_test 1.0   --with_rgb_loss  --batch_size 1 --pad 24 --ckpt ./ckpts/mvsnerf-v0.tar --N_vis 10 --net_type v3 --netchunk 100000 

#python train_gs_mvs_nerf_finetuning_pl.py --dataset_name dtu_ft_gs --datadir /rds/user/hl589/hpc-work/data/dtu_example/scan114 --savedir /rds/project/rds-JDeuXlFW9KE/hanxue_project/mvsnerf_exp --expname singleimage_pointloss_multi_volume_scan114_gs-mvsnerf-ft-lr1e-4 --withpointrgbloss --num_epochs 60000  --multi_volume --lrate 0.0001  --imgScale_test 1.0   --with_rgb_loss  --batch_size 1 --pad 24 --ckpt ./ckpts/mvsnerf-v0.tar --N_vis 10 --net_type v3 --netchunk 100000 

#python train_gs_mvs_nerf_finetuning_pl.py --dataset_name dtu_ft_gs --datadir /rds/user/hl589/hpc-work/data/dtu_example/scan114 --savedir /rds/project/rds-JDeuXlFW9KE/hanxue_project/mvsnerf_exp --expname singlescene_nopointloss_multi_volume_scan114_gs-mvsnerf-ft-lr1e-4 --increaseactivation_step 300000 --num_epochs 10000  --multi_volume --lrate 0.0001  --imgScale_test 1.0   --with_rgb_loss  --batch_size 1 --pad 24 --ckpt ./ckpts/mvsnerf-v0.tar --N_vis 50 --net_type v3 --netchunk 100000 

python train_gs_mvs_nerf_finetuning_pl.py --dataset_name dtu_ft_gs --datadir /rds/user/hl589/hpc-work/data/dtu_example/scan114 --savedir /rds/project/rds-JDeuXlFW9KE/hanxue_project/mvsnerf_exp --expname singlescene_pointloss_multi_volume_scan114_gs-mvsnerf-ft-lr1e-4 --withpointrgbloss --increaseactivation_step 300000 --num_epochs 10000  --multi_volume --lrate 0.0001  --imgScale_test 1.0   --with_rgb_loss  --batch_size 1 --pad 24 --ckpt ./ckpts/mvsnerf-v0.tar --N_vis 50 --net_type v3 --netchunk 100000 