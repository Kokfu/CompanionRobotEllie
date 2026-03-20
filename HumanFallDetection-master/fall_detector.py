import openpifpaf
import torch
import argparse
import copy
import logging
import torch.multiprocessing as mp
import csv
from default_params import *
from algorithms import *
from helpers import last_ip
import os
import matplotlib.pyplot as plt

# Extra imports for frame-iterator mode
import time
import numpy as np
import cv2
import collections
from typing import Iterable

try:
    mp.set_start_method('spawn')
except RuntimeError:
    pass


class FallDetector:
    def __init__(self, t=DEFAULT_CONSEC_FRAMES):
        # kept for back-compat with original repo,
        # but confirmation now uses --fall_confirm_sec by default
        self.consecutive_frames = t
        self.args = self.cli()

    def cli(self):
        parser = argparse.ArgumentParser(
            description=__doc__,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )

        # openpifpaf standard args
        openpifpaf.network.Factory.cli(parser)
        openpifpaf.decoder.cli(parser)

        # existing repo args
        parser.add_argument('--resolution', default=0.4, type=float,
                            help='Resolution prescale factor from 640x480. Rounded to multiples of 16.')
        parser.add_argument('--resize', default=None, type=str,
                            help='Force input image resize. Example WIDTHxHEIGHT.')
        parser.add_argument('--num_cams', default=1, type=int,
                            help='Number of Cameras.')
        parser.add_argument('--video', default=None, type=str,
                            help=('Path to the video file.\n'
                                  'For single video (--num_cams=1), save as abc.xyz and set --video=abc.xyz\n'
                                  'For two videos (--num_cams=2), save as abc1.xyz & abc2.xyz and set --video=abc.xyz'))
        parser.add_argument('--debug', default=False, action='store_true',
                            help='debug messages and autoreload')
        parser.add_argument('--disable_cuda', default=False, action='store_true',
                            help='disables cuda support and runs from gpu')

        vis_args = parser.add_argument_group('Visualisation')
        vis_args.add_argument('--plot_graph', default=False, action='store_true',
                              help='Plot features graph.')
        vis_args.add_argument('--joints', default=True, action='store_true',
                              help='Draw joints.')
        vis_args.add_argument('--skeleton', default=True, action='store_true',
                              help='Draw skeleton.')
        vis_args.add_argument('--coco_points', default=False, action='store_true',
                              help='Visualise COCO points.')
        vis_args.add_argument('--save_output', default=False, action='store_true',
                              help='Save result video in ./outputs/.')
        vis_args.add_argument('--fps', default=18, type=int,
                              help='Output/processing FPS.')

        # NEW: robust, FPS-independent fall settings
        parser.add_argument('--fall_confirm_sec', default=1.0, type=float,
                            help='Seconds of fall-like posture required before alert.')
        parser.add_argument('--fall_aspect', default=0.75, type=float,
                            help='h/w aspect threshold (smaller = flatter posture).')
        parser.add_argument('--fall_tilt_deg', default=40.0, type=float,
                            help='Torso tilt angle threshold in degrees.')
        parser.add_argument('--skip', default=0, type=int,
                            help='Process every (skip+1)th frame to save CPU.')
        parser.add_argument('--no_window', default=False, action='store_true',
                            help='Do not show OpenCV window.')

        args = parser.parse_args()

        # logging
        logging.basicConfig(level=logging.INFO if not args.debug else logging.DEBUG)
        # quiet down openpifpaf chatter
        logging.getLogger('openpifpaf').setLevel(logging.WARNING)
        logging.getLogger('openpifpaf.predictor').setLevel(logging.WARNING)
        logging.getLogger('openpifpaf.decoder.cifcaf').setLevel(logging.WARNING)

        # legacy repo defaults
        args.force_complete_pose = True
        args.instance_threshold = 0.2
        args.seed_threshold = 0.5

        # device
        args.device = torch.device('cpu')
        args.pin_memory = False
        if not args.disable_cuda and torch.cuda.is_available():
            args.device = torch.device('cuda')
            args.pin_memory = True

        # CPU-friendly checkpoint default
        if getattr(args, 'checkpoint', None) is None:
            args.checkpoint = 'shufflenetv2k16'

        openpifpaf.decoder.configure(args)
        openpifpaf.network.Factory.configure(args)
        return args

    # ---------------------------
    # ORIGINAL ENTRY (kept)
    # ---------------------------
    def begin(self):
        """Original repo path (webcam/multi-cam + LSTM pipeline)."""
        print('Starting...')
        e = mp.Event()
        queues = [mp.Queue() for _ in range(self.args.num_cams)]
        counter1 = mp.Value('i', 0)
        counter2 = mp.Value('i', 0)
        argss = [copy.deepcopy(self.args) for _ in range(self.args.num_cams)]
        if self.args.num_cams == 1:
            if self.args.video is None:
                argss[0].video = 0
            process1 = mp.Process(target=extract_keypoints_parallel,
                                  args=(queues[0], argss[0], counter1, counter2, self.consecutive_frames, e))
            process1.start()
            if self.args.coco_points:
                process1.join()
            else:
                process2 = mp.Process(target=alg2_sequential,
                                      args=(queues, argss, self.consecutive_frames, e))
                process2.start()
            process1.join()
        elif self.args.num_cams == 2:
            if self.args.video is None:
                argss[0].video = 0
                argss[1].video = 1
            else:
                try:
                    vid_name = self.args.video.split('.')
                    argss[0].video = ''.join(vid_name[:-1]) + '1.' + vid_name[-1]
                    argss[1].video = ''.join(vid_name[:-1]) + '2.' + vid_name[-1]
                    print('Video 1:', argss[0].video)
                    print('Video 2:', argss[1].video)
                except Exception:
                    print('Error: argument --video not properly set')
                    print('For 2 video fall detection (--num_cams=2), save your videos as abc1.xyz & abc2.xyz and set --video=abc.xyz')
                    return
            process1_1 = mp.Process(target=extract_keypoints_parallel,
                                    args=(queues[0], argss[0], counter1, counter2, self.consecutive_frames, e))
            process1_2 = mp.Process(target=extract_keypoints_parallel,
                                    args=(queues[1], argss[1], counter2, counter1, self.consecutive_frames, e))
            process1_1.start()
            process1_2.start()
            if self.args.coco_points:
                process1_1.join()
                process1_2.join()
            else:
                process2 = mp.Process(target=alg2_sequential,
                                      args=(queues, argss, self.consecutive_frames, e))
                process2.start()
            process1_1.join()
            process1_2.join()
        else:
            print('More than 2 cameras are currently not supported')
            return

        if not self.args.coco_points:
            process2.join()
        print('Exiting...')
        return

    # -------------------------------------------------------------------------
    # NEW: Frame-iterator entry for ROS 2 integration / videos
    # -------------------------------------------------------------------------
    def run_with_frames(self, frame_iter: Iterable[np.ndarray]):
        """
        Process frames from an external iterator/generator (e.g., ROS 2 subscriber or a video).
        """
        args = self.args
        logger = logging.getLogger('fall_iter')

        # Build predictor with safe checkpoint fallback
        def build_predictor(ckpt: str):
            try:
                return openpifpaf.Predictor(checkpoint=ckpt)
            except Exception as e:
                logger.warning(f'Checkpoint "{ckpt}" not found; falling back to "shufflenetv2k16". '
                               f'Original error: {e}')
                return openpifpaf.Predictor(checkpoint='shufflenetv2k16')

        predictor = build_predictor(args.checkpoint)

        # prepare resize
        target_size = None
        if args.resize:
            try:
                w, h = args.resize.lower().split('x')
                target_size = (int(w), int(h))
            except Exception:
                logger.warning('Invalid --resize, expected WIDTHxHEIGHT (e.g., 640x360). Ignoring.')

        prescale = float(args.resolution)

        # optional video writer
        writer = None
        out_path = None
        if args.save_output:
            os.makedirs('outputs', exist_ok=True)
            out_path = os.path.join('outputs', f'out_stream_{int(time.time())}.mp4')
            writer = None  # init lazily on first frame

        # state
        consec_fall_like = 0
        FALL_MSG_COOLDOWN = max(1, int(args.fps * 1.0))  # ~1 second of sticky label
        say_cooldown = 0

        # confirmation frames from seconds (FPS-independent)
        confirm_frames = max(1, int(args.fps * float(args.fall_confirm_sec)))

        def draw_pose(img, keypoints_xyv, draw_joints=True, draw_skeleton=True):
            kps = keypoints_xyv
            if draw_joints:
                for x, y, v in kps:
                    if v > 0.1:
                        cv2.circle(img, (int(x), int(y)), 3, (0, 255, 255), -1)
            if draw_skeleton:
                skeleton = [
                    (0, 1), (1, 3), (0, 2), (2, 4),
                    (5, 7), (7, 9), (6, 8), (8, 10),
                    (5, 6), (5, 11), (6, 12),
                    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)
                ]
                for i, j in skeleton:
                    if i < len(kps) and j < len(kps):
                        xi, yi, vi = kps[i]
                        xj, yj, vj = kps[j]
                        if vi > 0.1 and vj > 0.1:
                            cv2.line(img, (int(xi), int(yi)), (int(xj), int(yj)), (0, 255, 0), 2)

        def fall_heuristic(keypoints_xyv) -> bool:
            # bbox vert-ness + torso tilt
            kps = keypoints_xyv
            valid = kps[:, 2] > 0.1
            if valid.sum() < 5:
                return False

            xs = kps[valid, 0]
            ys = kps[valid, 1]
            w = (xs.max() - xs.min()) + 1e-6
            h = (ys.max() - ys.min()) + 1e-6
            aspect = h / w  # small => lying

            # shoulders (5,6), hips (11,12)
            needed = [5, 6, 11, 12]
            if not all(i < len(kps) for i in needed):
                return False
            if min(kps[5, 2], kps[6, 2], kps[11, 2], kps[12, 2]) <= 0.1:
                return False

            shoulder_mid = np.array([(kps[5, 0] + kps[6, 0]) / 2.0, (kps[5, 1] + kps[6, 1]) / 2.0])
            hip_mid = np.array([(kps[11, 0] + kps[12, 0]) / 2.0, (kps[11, 1] + kps[12, 1]) / 2.0])
            v = hip_mid - shoulder_mid
            up = np.array([0.0, -1.0])
            v_norm = v / (np.linalg.norm(v) + 1e-6)
            cosang = float(np.clip(np.dot(v_norm, up), -1.0, 1.0))
            ang_deg = np.degrees(np.arccos(cosang))

            return (aspect < float(args.fall_aspect)) and (ang_deg > float(args.fall_tilt_deg))

        def init_writer_if_needed(wr, path, frame_bgr, fps):
            if wr is not None:
                return wr
            h, w = frame_bgr.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            return cv2.VideoWriter(path, fourcc, fps, (w, h))

        min_dt = 1.0 / max(1, int(args.fps))
        last_t = 0.0

        logger.info('Running fall detection with external frame iterator...')
        try:
            i = 0
            for frame_bgr in frame_iter:
                i += 1
                # optional frame skipping
                if args.skip > 0 and (i % (args.skip + 1)) != 1:
                    continue

                now = time.time()
                if now - last_t < min_dt:
                    time.sleep(max(0.0, min_dt - (now - last_t)))
                last_t = time.time()

                if frame_bgr is None:
                    continue

                img = frame_bgr
                if target_size is not None:
                    img = cv2.resize(img, target_size, interpolation=cv2.INTER_AREA)
                elif prescale != 1.0:
                    h, w = img.shape[:2]
                    tw = max(16, int(640 * prescale) // 16 * 16)
                    th = max(16, int(480 * prescale) // 16 * 16)
                    img = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)

                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

                preds, _, _ = predictor.numpy_image(rgb)

                best_person = None
                best_score = -1.0
                for ann in preds:
                    if not hasattr(ann, 'data'):
                        continue
                    kxyv = ann.data
                    if kxyv is None or len(kxyv) == 0:
                        continue
                    score = float((kxyv[:, 2] > 0.1).sum())
                    if score > best_score:
                        best_score = score
                        best_person = kxyv

                fall_flag = False
                bbox = None
                if best_person is not None:
                    fall_flag = fall_heuristic(best_person)

                    # draw pose
                    if args.joints or args.skeleton:
                        draw_pose(img, best_person, draw_joints=args.joints, draw_skeleton=args.skeleton)

                    # compute a bbox for overlay
                    valid = best_person[:, 2] > 0.1
                    if np.any(valid):
                        xs = best_person[valid, 0]
                        ys = best_person[valid, 1]
                        xmin, xmax = int(xs.min()), int(xs.max())
                        ymin, ymax = int(ys.min()), int(ys.max())
                        bbox = (xmin, ymin, xmax, ymax)

                # maintain consecutive counter
                consec_fall_like = consec_fall_like + 1 if fall_flag else max(0, consec_fall_like - 1)

                # decision
                detected = consec_fall_like >= confirm_frames
                if detected and say_cooldown == 0:
                    logger.warning('FALL DETECTED')
                    say_cooldown = FALL_MSG_COOLDOWN

                # overlays
                if bbox is not None and (fall_flag or detected):
                    (xmin, ymin, xmax, ymax) = bbox
                    cv2.rectangle(img, (xmin, ymin), (xmax, ymax), (0, 0, 255), 2)
                if say_cooldown > 0:
                    say_cooldown -= 1
                    cv2.putText(img, 'FALL DETECTED', (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3, cv2.LINE_AA)

                if not args.no_window:
                    cv2.imshow('Fall Detection (frames)', img)
                    if (cv2.waitKey(1) & 0xFF) == 27:
                        break

                if args.save_output:
                    writer = init_writer_if_needed(writer, out_path, img, args.fps)
                    writer.write(img)

        finally:
            if writer is not None:
                writer.release()
            if not args.no_window:
                cv2.destroyAllWindows()


def _frames_from_video(path, resize_opt: str or None, prescale: float):
    """Simple generator to stream frames from a video file."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print(f'[ERROR] cannot open video: {path}')
        return
    # parse --resize once here (saves CPU per-frame)
    target_size = None
    if resize_opt:
        try:
            w, h = resize_opt.lower().split('x')
            target_size = (int(w), int(h))
        except Exception:
            pass
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        # apply same resize policy as run_with_frames()
        if target_size is not None:
            frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
        elif prescale != 1.0:
            h, w = frame.shape[:2]
            tw = max(16, int(640 * prescale) // 16 * 16)
            th = max(16, int(480 * prescale) // 16 * 16)
            frame = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_AREA)
        yield frame
    cap.release()


if __name__ == "__main__":
    fd = FallDetector()
    if fd.args.video:
        # drive frames into the same pipeline the ROS2 node uses
        fd.run_with_frames(_frames_from_video(fd.args.video, fd.args.resize, float(fd.args.resolution)))
    else:
        # fall back to original multiprocessing path (webcam / multi-cam)
        fd.begin()

