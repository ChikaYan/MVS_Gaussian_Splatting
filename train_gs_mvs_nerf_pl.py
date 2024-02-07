from opt import config_parser
from torch.utils.data import DataLoader
import pdb
from data import dataset_dict
from plyfile import PlyData, PlyElement
# models
from models import *
from renderer import *
from utils import *
from data.ray_utils import ray_marcher,ray_marcher_fine,get_rays
import math
import imageio
from diff_gaussian_rasterization import GaussianRasterizationSettings, GaussianRasterizer
import torchvision
# pytorch-lightning
from pytorch_lightning.callbacks import ModelCheckpoint
from pytorch_lightning import LightningModule, Trainer, loggers
import yaml
from pathlib import Path
import lpips

# device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
import lpips
lpips_vgg = lpips.LPIPS(net="vgg").eval().to(device)
class SL1Loss(nn.Module):
    def __init__(self, levels=3):
        super(SL1Loss, self).__init__()
        self.levels = levels
        self.loss = nn.SmoothL1Loss(reduction='mean')

    def forward(self, depth_pred, depth_gt, mask=None):
        if None == mask:
            mask = depth_gt > 0
        loss = self.loss(depth_pred[mask], depth_gt[mask]) * 2 ** (1 - 2)
        return loss

class MVSSystem(LightningModule):
    def __init__(self, args):
        super(MVSSystem, self).__init__()
        self.args = args
        self.args.feat_dim = args.volume_feat_outputdim+self.args.n_views*4 ##hanxue to edit
        self.args.dir_dim = 3
        self.use_mask = True
        Path(f'{args.savedir}/{args.expname}/').mkdir(exist_ok=True, parents=True)
        self.idx = 0

        with Path(f'{args.savedir}/{args.expname}/args.yaml').open('w') as f:
            yaml.dump(args, f)
        self.active_sh_degree = 0
        self.savedir = args.savedir

        self.loss = SL1Loss()
        self.lpips_fn = [lpips.LPIPS(net='vgg').eval()]
        self.mrf_fn = [IDMRFLoss().eval()]

        # Create nerf model
        ###hanxue
        self.render_kwargs_train, self.render_kwargs_test, start, self.grad_vars = create_nerf_mvs(args, use_mvs=True, dir_embedder=False, pts_embedder=True)
        self.start = start
        filter_keys(self.render_kwargs_train)

        # Create mvs model
        self.MVSNet = self.render_kwargs_train['network_mvs']
        self.render_kwargs_train.pop('network_mvs')
        self.render_kwargs_train['NDC_local'] = False
        self.eval_metric = [0.01,0.05, 0.1]
        dataset = dataset_dict[self.args.dataset_name]
        self.train_dataset = dataset(args, split='train', n_views=args.n_views,max_len=-1)# , downSample=args.imgScale_train)
        if self.args.val_only:
            self.val_dataset   = dataset(args, split='test',n_views=args.n_views, max_len=-1)#
        else:
            self.val_dataset   = dataset(args, split='test',n_views=args.n_views, max_len=10)# , downSample=args.imgScale_test)#

        self.model_register = self.render_kwargs_train['network_fn']
        self.MVSNet_register_fine = self.render_kwargs_train['network_fine']
        # pc_path = os.path.join(self.train_dataset.pointcloud_dir,f'Pointclouds10/scan114_pointclouds.npy')
        # init_pointclouds = np.load(pc_path)
        # self.init_pointclouds = torch.tensor(init_pointclouds).float()


        # dataset = dataset_dict[self.args.dataset_name]
        # self.train_dataset = dataset(args, split='train')
        # self.val_dataset   = dataset(args, split='val')
        # self.init_volume()
        # if args.multi_volume:
        #     print('we are using multi volume')
        #     for i in range(len(self.volume)):
        #         self.grad_vars += list(self.volume[i].parameters())
        # else:
        #     if args.dataset_name=='dtu_ft_gs':
        #         self.grad_vars.append({'params': self.volume.parameters(), 'lr': args.volume_lr, "name": "volume"})
        #     else:
        #         self.grad_vars += list(self.volume.parameters())
        # print(self.grad_vars)

    # def init_volume(self):

    #     self.imgs, self.proj_mats, self.near_far_source, self.pose_source = self.train_dataset.read_source_views(device=device)
    #     ckpts = None
    #     if args.ckpt is not None and args.ckpt != 'None':
    #         ckpts = torch.load(args.ckpt)
    #     if ckpts is not None:
    #         # print('ckpts keys',ckpts.keys()) dict_keys(['start', 'network_fn_state_dict', 'network_mvs_state_dict'])
    #         if 'volume' not in ckpts.keys():
    #             self.MVSNet.train()
    #             with torch.no_grad():
    #                 volume_feature, _, _ = self.MVSNet(self.imgs, self.proj_mats, self.near_far_source, pad=args.pad, lindisp=args.use_disp)
    #         else:
    #             volume_feature = ckpts['volume']['feat_volume']
    #             print('load ckpt volume.')
    #     self.imgs = self.unpreprocess(self.imgs)

    #     # project colors to a volume
    #     self.density_volume = None
    #     if args.use_color_volume or args.use_density_volume:
    #         D,H,W = volume_feature.shape[-3:]
    #         intrinsic, c2w = self.pose_source['intrinsics'][0].clone(), self.pose_source['c2ws'][0]
    #         intrinsic[:2] /= 4
    #         vox_pts = get_ptsvolume(H-2*args.pad,W-2*args.pad,D, args.pad,  self.near_far_source, intrinsic, c2w)

    #         self.color_feature = build_color_volume(vox_pts, self.pose_source, self.imgs, with_mask=True).view(D,H,W,-1).unsqueeze(0).permute(0, 4, 1, 2, 3)  # [N,D,H,W,C]
    #         if args.use_color_volume:
    #             volume_feature = torch.cat((volume_feature, self.color_feature),dim=1) # [N,C,D,H,W]

    #         if args.use_density_volume:
    #             self.vox_pts = vox_pts

    #         else:
    #             del vox_pts
    #     if args.multi_volume:
    #         self.volume =[]
    #         for i in range(4):
    #             self.volume.append(RefVolume(volume_feature.detach()).to(device))
    #     else:
    #         self.volume = RefVolume(volume_feature.detach()).to(device)
    #     del volume_feature

    def update_density_volume(self):
        with torch.no_grad():
            network_fn = self.render_kwargs_train['network_fn']
            network_query_fn = self.render_kwargs_train['network_query_fn']

            D,H,W = self.volume.feat_volume.shape[-3:]
            features = torch.cat((self.volume.feat_volume, self.color_feature), dim=1).permute(0,2,3,4,1).reshape(D*H,W,-1)
            self.density_volume = render_density(network_fn, self.vox_pts, features, network_query_fn).reshape(D,H,W)
        del features

    def decode_batch(self, batch):
        rays = batch['rays'].squeeze()  # (B, 8)
        rgbs = batch['rgbs'].squeeze()  # (3,H,W)
        R = batch['R'].squeeze()
        T = batch['T'].squeeze()
        mask = batch['mask'].squeeze()
        FovX = batch['FovX'].squeeze()
        FovY = batch['FovY'].squeeze()
        # target_proj_mat_ls = batch['target_proj_mat_ls'].squeeze()
        target_w2c = batch['target_w2c'].squeeze()
        target_intrinsics = batch['target_intrinsics'].squeeze()
        target_c2w = batch['target_c2w'].squeeze()
        
        return rays, rgbs, R, T, mask, FovX, FovY,target_w2c,target_c2w,target_intrinsics# target_projectmatric

    def unpreprocess(self, data, shape=(1,1,3,1,1)):
        # to unnormalize image for visualization
        device = data.device
        mean = torch.tensor([-0.485 / 0.229, -0.456 / 0.224, -0.406 / 0.225]).view(*shape).to(device)
        std = torch.tensor([1 / 0.229, 1 / 0.224, 1 / 0.225]).view(*shape).to(device)
        return (data - mean) / std

    def forward(self):
        return


    def configure_optimizers(self):
        print('type of self.grad_vars[0] is',type(self.grad_vars[0]))
        if self.args.multi_volume:
            self.optimizer = torch.optim.Adam(self.grad_vars, lr=self.args.lrate, betas=(0.9, 0.999))
        else:
            if args.dataset_name=='dtu_ft_gs':
                self.optimizer = torch.optim.Adam(self.grad_vars, betas=(0.9, 0.999))
            else:
                self.optimizer = torch.optim.Adam(self.grad_vars, lr=self.args.lrate, betas=(0.9, 0.999))
        # scheduler = get_scheduler(self.args, self.optimizer)
        eps = 1e-7
        scheduler = CosineAnnealingLR(self.optimizer, T_max=self.args.num_epochs, eta_min=eps)
        return [self.optimizer], [scheduler]

    def get_lr(self):
        for param_group in self.optimizer.param_groups:
            return param_group['lr']

    def train_dataloader(self):
        traindataloader = DataLoader(self.train_dataset,
                          shuffle=True,
                          num_workers=8,
                          batch_size=1,
                          pin_memory=True)
        # print('======================length of train dataloader is:',len(traindataloader))
        return traindataloader

    def val_dataloader(self):
        valdataloader = DataLoader(self.val_dataset,
                          shuffle=False,
                          num_workers=1,
                          batch_size=1,
                          pin_memory=True)
        print('======================length of val dataloader is:',len(valdataloader))
        return valdataloader
    def getWorld2View2(self,R, t, translate=np.array([.0, .0, .0]), scale=1.0):
        Rt = torch.zeros((4, 4))
        Rt[:3, :3] = R.transpose(1,0)
        Rt[:3, 3] = t
        Rt[3, 3] = 1.0

        C2W = torch.linalg.inv(Rt)
        cam_center = C2W[:3, 3]
        cam_center = (cam_center + translate) * scale
        C2W[:3, 3] = cam_center
        Rt = torch.linalg.inv(C2W)
        return Rt #np.float32(Rt)
    
    def getProjectionMatrix(self, znear, zfar, fovX, fovY):
        tanHalfFovY = math.tan((fovY / 2))
        tanHalfFovX = math.tan((fovX / 2))

        top = tanHalfFovY * znear
        bottom = -top
        right = tanHalfFovX * znear
        left = -right

        P = torch.zeros(4, 4)

        z_sign = 1.0

        P[0, 0] = 2.0 * znear / (right - left)
        P[1, 1] = 2.0 * znear / (top - bottom)
        P[0, 2] = (right + left) / (right - left)
        P[1, 2] = (top + bottom) / (top - bottom)
        P[3, 2] = z_sign
        P[2, 2] = z_sign * zfar / (zfar - znear)
        P[2, 3] = -(zfar * znear) / (zfar - znear)
        return P
    
    def on_train_start(self) -> None:
        # move lpips and mrf fn
        self.lpips_fn[0].to(self.device)
        self.mrf_fn[0].to(self.device)
    
    def training_step(self, batch, batch_nb):
        if self.global_step%self.args.increaseactivation_step==0:
            self.active_sh_degree=min(self.active_sh_degree+1,3)
            print('self.active_sh_degree',self.active_sh_degree)
        self.start = self.start+1
        zfar = 100.0
        znear = 0.01
        rays, rgbs_target, R, T, mask, FovX, FovY, target_w2c, target_c2w, target_intrinsics = self.decode_batch(batch)
        target_projectmatric = target_intrinsics @ target_w2c[:3, :4]
        if 'scan' in batch:
            # DTU dataset
            scan = batch['scan']
            light_idx = batch['light_idx']
            pair_idx = batch['src_views']
            scan = scan[0]
            # print('during train step, scan, light_idx, pair_idx',scan, light_idx, pair_idx)

            src_imgs, proj_mats, near_far_source, pose_source = self.train_dataset.read_source_views(scan, light_idx=light_idx, pair_idx=pair_idx,device=self.device)
        elif 'obj_idx' in batch:
            # Google scanned object
            scan = batch['obj_name'][0]
            src_imgs, proj_mats, _, pose_source = self.train_dataset.read_source_views(batch['obj_idx'].item(), pair_idx=batch['src_views'],device=self.device)
            near_far_source = batch['near_far'][0]
        # print('pose_source',pose_source['w2cs'].shape,pose_source['intrinsics'].shape,pose_source['c2ws'].shape)
        # torch.Size([3, 4, 4]) torch.Size([3, 3, 3]) torch.Size([3, 4, 4])
        H,W = src_imgs.shape[-2:]
        # print('during train step,',H,W)
        if self.args.multi_volume:
            volume_feature = []
            for i in range(len(self.MVSNet)):
                # self.MVSNet[i].eval() #hanxue
                volume_feature_, _, _ = self.MVSNet[i](src_imgs, proj_mats, near_far_source, pad=self.args.pad, lindisp=self.args.use_disp)
                volume_feature.append(volume_feature_)
        else:
            volume_feature, _, _ = self.MVSNet(src_imgs, proj_mats, near_far_source, pad=self.args.pad, lindisp=self.args.use_disp)
            

        world_view_transform = self.getWorld2View2(R, T).transpose(0, 1).to(self.device)
        projection_matrix = self.getProjectionMatrix(znear=znear, zfar=zfar, fovX=FovX, fovY=FovY).transpose(0,1).to(self.device)
        full_proj_transform = (world_view_transform.unsqueeze(0).bmm(projection_matrix.unsqueeze(0))).squeeze(0)
        camera_center = world_view_transform.inverse()[3, :3]

        # Set up rasterization configuration
        tanfovx = math.tan(FovX * 0.5)
        tanfovy = math.tan(FovY * 0.5)
        bg_color = [0, 0, 0]
        bg_color = torch.tensor(bg_color, dtype=torch.float32, device=self.device)
        raster_settings = GaussianRasterizationSettings(
            image_height=int(H),
            image_width=int(W),
            tanfovx=tanfovx,
            tanfovy=tanfovy,
            bg=bg_color,
            scale_modifier=1.0,
            viewmatrix=world_view_transform,
            projmatrix=full_proj_transform,
            sh_degree=self.active_sh_degree,
            campos=camera_center,
            prefiltered=False,
            debug=False,
        )

        rasterizer = GaussianRasterizer(raster_settings=raster_settings)

        if args.use_density_volume and 0 == self.start%200:
            self.update_density_volume()
        # rays_o, rays_d = rays[:, 0:3], rays[:, 3:6]
        mask = torch.tensor(mask,device=self.device).reshape(-1)

        # print('rays_d',rays_o.shape, rays_d.shape)
        # xyz_coarse_sampled, rays_o, rays_d, z_vals = ray_marcher(rays, N_samples=args.N_samples,
        #                 lindisp=args.use_disp, perturb=args.perturb) ##provide the xyz_coordinates in world system
        
        # xyz_coarse_sampled = self.train_dataset.init_pointclouds[:,:3].to(torch.device('cuda'))
        ext = 'npy' if self.args.pt_folder == 'Pointclouds10' or self.args.pt_folder == 'Pointclouds50' or self.args.pt_folder == 'Pointclouds10_scale0.05' else 'ply'
        pc_path = os.path.join(self.train_dataset.pointcloud_dir,f'{self.args.pt_folder}/{scan}_pointclouds.{ext}')
        init_pointclouds = load_pointcloud(pc_path)[::self.args.pt_downsample]
        init_pointclouds = torch.tensor(init_pointclouds).float()
        # init_pointclouds = self.init_pointclouds
        xyz_coarse_sampled = init_pointclouds[:,:3].to(self.device)

        point_coords = torch.cat((xyz_coarse_sampled,torch.ones(xyz_coarse_sampled.shape[0],1).to(self.device)),dim=1)@(target_projectmatric.T)
        point_coords = point_coords/point_coords[:,2:]
        point_coords = point_coords[:,:2].type(torch.int)
        center = [target_intrinsics[0,2], target_intrinsics[1,2]]
        focal = [target_intrinsics[0,0], target_intrinsics[1,1]]
        # print('point_coords[:,0]',torch.max(point_coords[:,0]),torch.min(point_coords[:,0]),torch.max(point_coords[:,1]),torch.min(point_coords[:,1]))
        directions = torch.stack([(point_coords[:,0] - center[0]) / focal[0], (point_coords[:,1] - center[1]) / focal[1], torch.ones_like(point_coords[:,0])], -1)  # (H, W, 3)
        # print('directions',directions.shape)
        rays_o, rays_d = get_rays(directions, target_c2w) 

        
        # Converting world coordinate to ndc coordinate
        
        inv_scale = torch.tensor([W - 1, H - 1]).to(self.device)
        w2c_ref, intrinsic_ref = pose_source['w2cs'][0], pose_source['intrinsics'][0]
        xyz_NDC = get_ndc_coordinate(w2c_ref, intrinsic_ref, xyz_coarse_sampled, inv_scale, \
                                     near=near_far_source[0],far=near_far_source[1], pad=args.pad, lindisp=args.use_disp)

        # important sampleing
        if args.N_importance > 0:
            xyz_coarse_sampled, rays_o, rays_d, z_vals = ray_marcher_fine(rays, self.density_volume, z_vals, xyz_NDC,
                                                                          N_importance=args.N_importance)
            xyz_NDC = get_ndc_coordinate(w2c_ref, intrinsic_ref, xyz_coarse_sampled, inv_scale,
                                         near=self.near_far_source[0], far=self.near_far_source[1], pad=args.pad, lindisp=args.use_disp)

        if args.use_viewdirs:
            opacity,scales,rotations,shs = rendering_gs(args, pose_source, xyz_coarse_sampled, xyz_NDC, None, rays_o, rays_d,
                                                        volume_feature, src_imgs,  **self.render_kwargs_train)
        else:
            opacity,scales,rotations,shs = rendering_gs(args, pose_source, xyz_coarse_sampled, xyz_NDC, None, None, None,
                                                       volume_feature, src_imgs,  **self.render_kwargs_train)
        scales = scales*self.args.decay_scale
        if not torch.max(scales)<=(self.args.decay_scale+0.0001):
            print('=====================torch.max(scales)===================',torch.max(scales))
        if args.singlescale:
            scales = scales.repeat(1,3)
            rotations = torch.zeros_like(rotations,device=self.device)
            rotations[:,0]=1
        means3D = xyz_coarse_sampled
        means2D = torch.zeros_like(means3D, dtype=means3D.dtype, device=self.device) + 0

        if self.args.use_precomp_color:
            colors_precomp = shs[:,0,:]
            pass_shs = None
        else:
            colors_precomp = None
            pass_shs = shs
        
        rendered_image, radii = rasterizer(
            means3D = means3D,
            means2D = means2D,
            shs = pass_shs,
            colors_precomp = colors_precomp,
            opacities = opacity,
            scales = scales,
            rotations = rotations,
            cov3D_precomp = None)

        # if self.start%1000==0:
        #     torchvision.utils.save_image(rendered_image, f'{self.savedir}/{self.args.expname}/train_{self.start:05d}' + ".png")
        #     torchvision.utils.save_image(rgbs_target, f'{self.savedir}/{self.args.expname}/traingt_{self.start:05d}' + ".png")
        
        log, loss = {}, 0
        # pdb.set_trace()
        
        # print('rgbs_target shape,',rgbs_target.shape, rendered_image.shape)
        if self.args.with_rgb_loss:
            if self.use_mask:
                img_loss = img2mse(rendered_image.permute(1,2,0).reshape(-1,3)[mask], rgbs_target.permute(1,2,0).reshape(-1,3)[mask])
            else:
                img_loss = img2mse(rendered_image,rgbs_target)
            loss += img_loss
            psnr = mse2psnr2(img_loss.item())

            lpips_loss = torch.tensor(0)
            mrf_loss = torch.tensor(0)
            if self.use_mask:
                Ll1 = (1.0 - 0.2)*l1_loss(rendered_image.permute(1,2,0).reshape(-1,3)[mask], rgbs_target.permute(1,2,0).reshape(-1,3)[mask])
                im_mask = mask.reshape([rendered_image.shape[1], rendered_image.shape[2]])[None, ...].repeat([3,1,1]).float()
                masked_rendered_image = rendered_image * im_mask
                masked_rgbs_target = rgbs_target * im_mask
                ssim_loss = (1.0 - ssim(masked_rendered_image, masked_rgbs_target))
                if self.args.lambda_lpips > 0:
                    centered_masked_rendered_image = (masked_rendered_image - 0.5) * 2
                    centered_masked_rgbs_target = (masked_rgbs_target.type_as(centered_masked_rendered_image) - 0.5) * 2
                    lpips_loss = self.lpips_fn[0](centered_masked_rendered_image.unsqueeze(0), centered_masked_rgbs_target.unsqueeze(0)).mean()
                if self.args.lambda_mrf > 0:
                    mrf_loss = self.mrf_fn[0](masked_rendered_image.unsqueeze(0), masked_rgbs_target.unsqueeze(0)).mean()
                    
            else:
                Ll1 = (1.0 - 0.2)*l1_loss(rendered_image, rgbs_target)
                ssim_loss = (1.0 - ssim(rendered_image, rgbs_target))
                if self.args.lambda_lpips > 0:
                    centered_masked_rendered_image = (rendered_image - 0.5) * 2
                    centered_masked_rgbs_target = (rgbs_target - 0.5) * 2
                    lpips_loss = self.lpips_fn[0](centered_masked_rendered_image.unsqueeze(0), centered_masked_rgbs_target.unsqueeze(0)).mean()
                if self.args.lambda_mrf > 0:
                    mrf_loss = self.mrf_fn[0](rendered_image.unsqueeze(0), rgbs_target.unsqueeze(0)).mean()

            loss += Ll1
            loss += self.args.lambda_dssim * ssim_loss
            loss += self.args.lambda_lpips * lpips_loss



            # if self.use_mask:
            #     Ll1 = (1.0 - 0.2)*l1_loss(rendered_image.permute(1,2,0).reshape(-1,3)[mask], rgbs_target.permute(1,2,0).reshape(-1,3)[mask])
            #     im_mask = mask.reshape([rendered_image.shape[1], rendered_image.shape[2]])[None, ...].repeat([3,1,1]).float()
            #     masked_rendered_image = rendered_image * im_mask
            #     masked_rgbs_target = rgbs_target * im_mask
            # else:
            #     Ll1 = (1.0 - 0.2)*l1_loss(rendered_image, rgbs_target)
            #     ssim_loss = (1.0 - ssim(rendered_image, rgbs_target))
            #     masked_rendered_image = rendered_image
            #     masked_rgbs_target = rgbs_target

            # ssim_loss = (1.0 - ssim(masked_rendered_image, masked_rgbs_target))

            # if self.args.lambda_lpips > 0:
            #     centered_masked_rendered_image = (masked_rendered_image - 0.5) * 2
            #     centered_masked_rgbs_target = (masked_rgbs_target.type_as(centered_masked_rendered_image) - 0.5) * 2
            #     lpips_loss = self.lpips_fn[0](centered_masked_rendered_image.unsqueeze(0), centered_masked_rgbs_target.unsqueeze(0)).mean()

            # if self.args.lambda_mrf > 0:
            #     pass
            #     # mrf_loss = self.mrf_fn[0](masked_rendered_image.unsqueeze(0), masked_rgbs_target.unsqueeze(0)).mean()



            if self.args.withpointrgbloss:
                point_rgb = init_pointclouds[:,3:].to(self.device)
                point_rbg_loss = l2_loss(shs[:,0,:],point_rgb)
                loss+=point_rbg_loss
                point_Ll1 = (1.0 - 0.2)*l1_loss(shs[:,0,:], point_rgb)
                loss += point_Ll1
            with torch.no_grad():
                self.log('train/loss', loss, prog_bar=True)
                self.log('train/img_mse_loss', img_loss.item(), prog_bar=False)
                self.log('train/PSNR', psnr.item(), prog_bar=True)
                self.log('train/Ll1', Ll1.item(), prog_bar=False)
                if self.args.withpointrgbloss:
                    self.log('train/pointL2', point_rbg_loss.item(), prog_bar=False)
                    self.log('train/pointL1', point_Ll1.item(), prog_bar=False)
                self.log('train/ssim_loss', ssim_loss.item(), prog_bar=False)
                self.log('train/lpips_loss', lpips_loss.item(), prog_bar=False)
                self.log('train/mrf_loss', mrf_loss.item(), prog_bar=False)
            if self.start%len(self.train_dataloader())==0:
                print('train/PSNR',psnr.item())
            if self.start%10000==0:
                # print('will set trace here')
                # import pdb; 
                # pdb.set_trace()
                rgbs = torch.clamp(rendered_image.permute([1,2,0]),0,1)#.cpu()
                img = rgbs_target.permute([1,2,0])#.cpu()
                #depth_r = torch.cat(depth_preds).reshape(H, W)
                img_err_abs = (rgbs - img).abs()
                # img_vis = torch.stack((img, rgbs, img_err_abs*5,im_mask)).permute(0,3,1,2)
                os.makedirs(f'{self.savedir}/{self.args.expname}/{self.args.expname}/',exist_ok=True)
                # print(img.device,type(img),rgbs.device,type(rgbs),img_err_abs.device,type(img_err_abs))
                img_vis = torch.cat((img,rgbs,img_err_abs*10,im_mask.permute([1,2,0])),dim=1).detach().cpu().numpy() #depth_r.permute(1,2,0)
                img_dir = Path(f'{self.savedir}/{self.args.expname}/train_rgb')
                img_dir.mkdir(exist_ok=True, parents=True)
                imageio.imwrite(str(img_dir / f"{self.start:08d}_{batch['idx'].item():02d}.png"), (img_vis*255).astype('uint8'))
                self.save_ckpt()
        return  {'loss':loss}


    def validation_step(self, batch, batch_idx):
        # if self.global_rank == 0:
        #     import pdb; pdb.set_trace()

        if isinstance(self.MVSNet,list) or isinstance(self.MVSNet,nn.ModuleList):
            for i in range(len(self.MVSNet)):
                self.MVSNet[i].train()
        else:
            self.MVSNet.train() #hanxue
        rays, img, R, T, mask, FovX, FovY,target_w2c,target_c2w,target_intrinsics = self.decode_batch(batch)
        target_projectmatric = target_intrinsics @ target_w2c[:3, :4]
        # rays_o, rays_d = rays[:, 0:3], rays[:, 3:6]
        # print('mask',mask.shape)
        mask = torch.tensor(mask,device=self.device).reshape(-1)

        # print('rays_o',rays_o.shape,rays_d.shape)
        if 'scan' in batch:
            # DTU dataset
            scan = batch['scan']
            light_idx = batch['light_idx']
            pair_idx = batch['src_views']
            scan = scan[0]
            # print('during train step, scan, light_idx, pair_idx',scan, light_idx, pair_idx)

            src_imgs, proj_mats, near_far_source, pose_source = self.train_dataset.read_source_views(scan, light_idx=light_idx, pair_idx=pair_idx,device=self.device)
        elif 'obj_idx' in batch:
            # Google scanned object
            scan = batch['obj_name'][0]
            src_imgs, proj_mats, _, pose_source = self.train_dataset.read_source_views(batch['obj_idx'].item(), pair_idx=batch['src_views'],device=self.device)
            near_far_source = batch['near_far'][0]

        if self.args.multi_volume:
            volume_feature = []
            for i in range(len(self.MVSNet)):
                volume_feature_, _, _ = self.MVSNet[i](src_imgs, proj_mats, near_far_source, pad=self.args.pad, lindisp=self.args.use_disp)
                volume_feature.append(volume_feature_)
        else:
            volume_feature, _, _ = self.MVSNet(src_imgs, proj_mats, near_far_source, pad=self.args.pad, lindisp=self.args.use_disp)
          
        zfar = 100.0
        znear = 0.01
        img = img.cpu()  # (3, H, W)
        H,W = img.shape[-2:]
        world_view_transform = self.getWorld2View2(R, T).transpose(0, 1).to(self.device)#torch.tensor(self.getWorld2View2(R, T)).transpose(0, 1).to(self.device)
        projection_matrix = self.getProjectionMatrix(znear=znear, zfar=zfar, fovX=FovX, fovY=FovY).transpose(0,1).to(self.device)
        full_proj_transform = (world_view_transform.unsqueeze(0).bmm(projection_matrix.unsqueeze(0))).squeeze(0)
        camera_center = world_view_transform.inverse()[3, :3]

        # Set up rasterization configuration
        tanfovx = math.tan(FovX * 0.5)
        tanfovy = math.tan(FovY * 0.5)
        bg_color = [0, 0, 0]
        bg_color = torch.tensor(bg_color, dtype=torch.float32, device=self.device)
        raster_settings = GaussianRasterizationSettings(
            image_height=int(H),
            image_width=int(W),
            tanfovx=tanfovx,
            tanfovy=tanfovy,
            bg=bg_color,
            scale_modifier=1.0,
            viewmatrix=world_view_transform,
            projmatrix=full_proj_transform,
            sh_degree=self.active_sh_degree,
            campos=camera_center,
            prefiltered=False,
            debug=False,
        )

        rasterizer = GaussianRasterizer(raster_settings=raster_settings)
        # xyz_coarse_sampled = self.train_dataset.init_pointclouds[:,:3].to(torch.device('cuda'))
        ext = 'npy' if self.args.pt_folder == 'Pointclouds10' or self.args.pt_folder == 'Pointclouds50' or self.args.pt_folder == 'Pointclouds10_scale0.05' else 'ply'
        pc_path = os.path.join(self.val_dataset.pointcloud_dir,f'{self.args.pt_folder}/{scan}_pointclouds.{ext}')
        init_pointclouds = load_pointcloud(pc_path)[::self.args.pt_downsample]
        init_pointclouds = torch.tensor(init_pointclouds).float()
        # init_pointclouds = self.init_pointclouds
        xyz_coarse_sampled = init_pointclouds[:,:3].to(self.device)
        # point_coords = (target_projectmatric@torch.cat((xyz_coarse_sampled,torch.ones(xyz_coarse_sampled.shape[0],1).to(self.device)),dim=1).T).T
        point_coords = torch.cat((xyz_coarse_sampled,torch.ones(xyz_coarse_sampled.shape[0],1).to(self.device)),dim=1)@target_projectmatric.T
        point_coords = point_coords/point_coords[:,2:]
        point_coords = point_coords[:,:2].type(torch.int)
        center = [target_intrinsics[0,2], target_intrinsics[1,2]]
        focal = [target_intrinsics[0,0], target_intrinsics[1,1]]
        # print('point_coords[:,0]',torch.max(point_coords[:,0]),torch.min(point_coords[:,0]),torch.max(point_coords[:,1]),torch.min(point_coords[:,1]))
        directions = torch.stack([(point_coords[:,0] - center[0]) / focal[0], (point_coords[:,1] - center[1]) / focal[1], torch.ones_like(point_coords[:,0])], -1)  # (H, W, 3)
        # print('directions',directions.shape)
        rays_o, rays_d = get_rays(directions, target_c2w) 
        # print('rays_o',rays_o.shape,rays_d.shape)
        N_rays_all = rays.shape[0]
        # print(xyz_coarse_sampled.dtype,R.dtype,T.dtype,rays.dtype) float32
        ##################  rendering #####################
        keys = ['val_psnr_all']
        log = init_log({}, keys)
        with torch.no_grad():
            rgbs, depth_preds = [],[]
            inv_scale = torch.tensor([W - 1, H - 1]).to(device)
            w2c_ref, intrinsic_ref = pose_source['w2cs'][0], pose_source['intrinsics'][0].clone()
            intrinsic_ref[:2] *= args.imgScale_test/args.imgScale_train
            xyz_NDC = get_ndc_coordinate(w2c_ref, intrinsic_ref, xyz_coarse_sampled, inv_scale,
                                            near=near_far_source[0], far=near_far_source[1], pad=args.pad*args.imgScale_test, lindisp=args.use_disp)
            if args.use_viewdirs:
                opacity,scales,rotations,shs = rendering_gs(args, pose_source, xyz_coarse_sampled, xyz_NDC, None, rays_o, rays_d,
                                                            volume_feature, src_imgs,  **self.render_kwargs_train)
            else:
                opacity,scales,rotations,shs = rendering_gs(args, pose_source, xyz_coarse_sampled, xyz_NDC, None, None, None,
                                                        volume_feature, src_imgs,  **self.render_kwargs_train)
            means3D = xyz_coarse_sampled
            means2D = torch.zeros_like(means3D, dtype=means3D.dtype, device=self.device) + 0
            scales = scales*self.args.decay_scale
            if not torch.max(scales)<=(self.args.decay_scale+0.0001):
                print('=====================torch.max(scales)===================',torch.max(scales))
            if args.singlescale:
                scales = scales.repeat(1,3)
                rotations = torch.zeros_like(rotations,device=self.device)
                rotations[:,0]=1
                # print('scales,rotations',scales.shape,rotations.shape)
                
            if self.args.use_precomp_color:
                colors_precomp = shs[:,0,:]
                pass_shs = None
            else:
                colors_precomp = None
                pass_shs = shs
            
            rgbs, radii = rasterizer(
                means3D = means3D,
                means2D = means2D,
                shs = pass_shs,
                colors_precomp = colors_precomp,
                opacities = opacity,
                scales = scales,
                rotations = rotations,
                cov3D_precomp = None)

            rgbs = torch.clamp(rgbs,0,1)
            if not self.use_mask:
                lpips_i = lpips_vgg(img[None, ...].to(device).contiguous(),rgbs[None, ...].to(device).contiguous(), normalize=True)#.item()
                ssim_i = ssim(img[None, ...].to(device).contiguous(), rgbs[None, ...].to(device).contiguous(), 11, True)#.item()
                log['val_lpips'] = lpips_i
                log['val_ssim'] = ssim_i

            rgbs = torch.clamp(rgbs.permute([1,2,0]),0,1).cpu()
            img = img.permute([1,2,0])
            #depth_r = torch.cat(depth_preds).reshape(H, W)
            img_err_abs = (rgbs - img).abs()
            im_mask = mask.reshape([rgbs.shape[0], rgbs.shape[1]])[...,None].repeat([1,1,3]).float()
            if self.use_mask:
                img_loss = img2mse(rgbs.reshape(-1,3)[mask], img.reshape(-1,3)[mask])
                log['val_psnr_all']  = mse2psnr2(img_loss)
            else:
                log['val_psnr_all'] = mse2psnr(torch.mean(img_err_abs ** 2))
            

            # img_vis = torch.stack((img, rgbs, img_err_abs.cpu()*5,im_mask)).permute(0,3,1,2)
            # self.logger.experiment.add_images('val/rgb_pred_err', img_vis, self.start)
            os.makedirs(f'{self.savedir}/{self.args.expname}/{self.args.expname}/',exist_ok=True)
            # print('im_mask',img.shape, rgbs.shape, im_mask.shape)
            img_vis = torch.cat((img,rgbs,img_err_abs*10,im_mask.cpu()),dim=1).numpy() #depth_r.permute(1,2,0)
            img_dir = Path(f'{self.savedir}/{self.args.expname}/val_rgb')
            if not args.nosave:
                if args.val_only:
                    os.makedirs(f'{self.savedir}/{self.args.expname}/val_only',exist_ok=True)
                    val_rgb_path = f'{self.savedir}/{self.args.expname}/val_only/{self.global_step:08d}_{self.idx:03d}.png'
                    imageio.imwrite(val_rgb_path,(img_vis*255).astype('uint8'))

                    # log ply
                    if batch_idx == 0:
                        feature_ds, feature_rest = shs[:,:1], shs[:,1:]
                        src_views = torch.stack(pair_idx).cpu().numpy()[:,0].tolist()
                        downsample_rate = 4
                        # import pdb; pdb.set_trace()
                        gs_save_ply(
                            means3D[::downsample_rate,...], feature_ds[::downsample_rate,...], feature_rest[::downsample_rate,...], opacity[::downsample_rate,...], scales[::downsample_rate,...], rotations[::downsample_rate,...],
                            f"{self.savedir}/{self.args.expname}/val_only_ply/{scan}_source_{src_views}.ply")
                else:
                    img_dir.mkdir(exist_ok=True, parents=True)
                    imageio.imwrite(str(img_dir / f"{self.start:08d}_{batch['idx'].item():02d}.png"), (img_vis*255).astype('uint8'))
        self.idx += 1
        return log

    def validation_epoch_end(self, outputs):
        # print('===========================================================================================================================================================================================================================================================error happens!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
        if self.args.with_depth:
            mean_psnr = torch.stack([x['val_psnr'] for x in outputs]).mean()
            mask_sum = torch.stack([x['mask_sum'] for x in outputs]).sum()
            # mean_d_loss_l = torch.stack([x['val_depth_loss_l'] for x in outputs]).mean()
            mean_d_loss_r = torch.stack([x['val_depth_loss_r'] for x in outputs]).mean()
            mean_abs_err = torch.stack([x['val_abs_err'] for x in outputs]).sum() / mask_sum
            mean_acc_1mm = torch.stack([x[f'val_acc_{self.eval_metric[0]}mm'] for x in outputs]).sum() / mask_sum
            mean_acc_2mm = torch.stack([x[f'val_acc_{self.eval_metric[1]}mm'] for x in outputs]).sum() / mask_sum
            mean_acc_4mm = torch.stack([x[f'val_acc_{self.eval_metric[2]}mm'] for x in outputs]).sum() / mask_sum

            self.log('val/d_loss_r', mean_d_loss_r, prog_bar=False)
            self.log('val/PSNR', mean_psnr, prog_bar=False)

            self.log('val/abs_err', mean_abs_err, prog_bar=False)
            self.log(f'val/acc_{self.eval_metric[0]}mm', mean_acc_1mm, prog_bar=False)
            self.log(f'val/acc_{self.eval_metric[1]}mm', mean_acc_2mm, prog_bar=False)
            self.log(f'val/acc_{self.eval_metric[2]}mm', mean_acc_4mm, prog_bar=False)

        mean_psnr_all = torch.stack([x['val_psnr_all'] for x in outputs]).mean()
        if not self.use_mask:
            mean_ssim = torch.stack([x['val_ssim'] for x in outputs]).mean()
            mean_lpips = torch.stack([x['val_lpips'] for x in outputs]).mean()

        if args.val_only:
            metric_path = f'{self.savedir}/{self.args.expname}/val_only_metrics.txt'
        else:
            metric_path = f'{self.savedir}/{self.args.expname}/metrics.txt'
        self.log('val/PSNR_all', mean_psnr_all, prog_bar=False)
        if not self.use_mask:
            self.log('val/ssim', mean_ssim, prog_bar=False)
            self.log('val/lpips', mean_lpips, prog_bar=False)
        with open(metric_path, 'a') as f:
            f.write('iter:'+str(self.global_step)+'\n') 
            f.write('num_testimages:'+str(len([x['val_psnr_all'] for x in outputs]))+'\n') 
            f.write('val/psnr:'+str(mean_psnr_all)+'\n') 
            if not self.use_mask:
                f.write('val/ssim:'+str(mean_ssim)+'\n')
                f.write('val/lpips:'+str(mean_lpips)+'\n')
        return

    def construct_list_of_attributes(self):
        l = ['x', 'y', 'z', 'nx', 'ny', 'nz']
        # All channels except the 3 DC
        for i in range(3):
            l.append('f_dc_{}'.format(i))
        for i in range(45):
            l.append('f_rest_{}'.format(i))
        l.append('opacity')
        for i in range(3):
            l.append('scale_{}'.format(i))
        for i in range(4):
            l.append('rot_{}'.format(i))
        return l
    
    def save_ckpt(self, name='latest'):
        save_dir = f'{self.savedir}/{self.args.expname}/ckpts/'
        os.makedirs(save_dir, exist_ok=True)
        path = f'{save_dir}/{name}.tar'
        ckpt = {
            'global_step': self.start,
            'network_fn_state_dict': self.render_kwargs_train['network_fn'].state_dict(),
            # 'volume': self.volume.state_dict(),
            'network_mvs_state_dict': self.MVSNet.state_dict()}
        if self.render_kwargs_train['network_fine'] is not None:
            ckpt['network_fine_state_dict'] = self.render_kwargs_train['network_fine'].state_dict()
        torch.save(ckpt, path)
        print('Saved checkpoints at', path)
        # path = f'{save_dir}/point_cloud.ply'
        # xyz = self.train_dataset.init_pointclouds[:,:3].numpy()
        # xyz_coarse_sampled = self.train_dataset.init_pointclouds[:,:3].to(torch.device('cuda'))
        # normals = np.zeros_like(xyz)
        # H,W = self.imgs.shape[-2:]
        # inv_scale = torch.tensor([W - 1, H - 1]).to(device)
        # w2c_ref, intrinsic_ref = pose_source['w2cs'][0], pose_source['intrinsics'][0].clone()
        # intrinsic_ref[:2] *= args.imgScale_test/args.imgScale_train
        # xyz_NDC = get_ndc_coordinate(w2c_ref, intrinsic_ref, xyz_coarse_sampled, inv_scale,
        #                                 near=self.near_far_source[0], far=self.near_far_source[1], pad=args.pad*args.imgScale_test, lindisp=args.use_disp)
        # opacity,scales,rotations,shs = rendering_gs(args, self.pose_source, xyz_coarse_sampled, xyz_NDC, None, None, None,
        #                                                 self.volume, self.imgs,  **self.render_kwargs_train)
        # f_dc = shs[:,0:1,:].detach().flatten(start_dim=1).contiguous().cpu().numpy()
        # f_rest = shs[:,1:,:].detach().flatten(start_dim=1).contiguous().cpu().numpy()
        # opacities = opacity.detach().cpu().numpy()
        # scale = scales.detach().cpu().numpy()
        # rotation = rotations.detach().cpu().numpy()

        # dtype_full = [(attribute, 'f4') for attribute in self.construct_list_of_attributes()]

        # elements = np.empty(xyz.shape[0], dtype=dtype_full)
        # attributes = np.concatenate((xyz, normals, f_dc, f_rest, opacities, scale, rotation), axis=1)
        # elements[:] = list(map(tuple, attributes))
        # el = PlyElement.describe(elements, 'vertex')
        # PlyData([el]).write(path)

if __name__ == '__main__':
    torch.set_default_dtype(torch.float32)
    args = config_parser()
    os.makedirs(f'{args.savedir}',exist_ok=True)
    print('saving check points at',f'{args.savedir}/{args.expname}')
    os.makedirs(f'{args.savedir}/{args.expname}',exist_ok=True)
    system = MVSSystem(args)
    print(system)
    # import pdb;pdb.set_trace()
    checkpoint_callback = ModelCheckpoint(os.path.join(f'{args.savedir}/{args.expname}/ckpts/','{epoch:02d}'),
                                          monitor='val/PSNR',
                                          mode='max',
                                          save_top_k=0)

    logger = loggers.TestTubeLogger(
        save_dir=args.savedir,
        name=args.expname,
        debug=False,
        create_git_tag=False
    )
    

    args.use_amp = False
    # args.num_gpus, args.use_amp = -1, False
    trainer = Trainer(max_epochs=args.num_epochs,
                      checkpoint_callback=checkpoint_callback,
                      logger=logger,
                      weights_summary=None,
                      progress_bar_refresh_rate=1,
                      gpus=args.num_gpus,
                      distributed_backend='ddp' if args.num_gpus != 1 else None,
                      num_sanity_val_steps=1, #if args.num_gpus > 1 else 5,
                      check_val_every_n_epoch = max(system.args.num_epochs//system.args.N_vis,1),
                    #   val_check_interval=int(max(system.args.num_epochs//system.args.N_vis,1)),
                      benchmark=True,
                      precision=16 if args.use_amp else 32,
                      amp_level='O1',
                    #   accelerator='ddp' if args.num_gpus != 1 else None,
                      )
    if args.val_only:
        trainer.validate(system)
    else:
        trainer.fit(system)
        system.save_ckpt()
