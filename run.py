import argparse
import logging
import time

import numpy as np

from config import detector_config
from detector import Detector
from lidar_map import LidarMap, lidar_config
from msgdev import MsgDevice
from utils import setup_logger, FPSTimer, Visualizer, ESC

EMPTY = -100


def build_push_data(object_dict, target):
    ret = []
    target_is_included = False
    target_index = EMPTY
    if object_dict:
        ret_list = sorted(object_dict.items(),
                          key=lambda v: (v[1]["centroid"][0] ** 2 + v[1]["centroid"][1] ** 2))
        for i, (k, v) in enumerate(ret_list[:3]):
            if k == target:
                target_is_included = True
                target_index = i
            ret.extend(v["centroid"].tolist())
    if len(ret) < 6:
        ret.extend([EMPTY] * (6 - len(ret)))
    if target and not target_is_included:
        ret[:2] = object_dict[target]["centroid"].tolist()
        target_index = 0
    ret.append(target_index)
    assert len(ret) == 7
    # print("Return of push data: ", ret)
    return ret


def build_push_detection_dev(push_detection_dev):
    push_detection_dev.open()
    push_detection_dev.pub_bind('tcp://0.0.0.0:55019')  # 上传端口


def build_pull_lidar_dev(pull_lidar_dev):
    pull_lidar_dev.open()
    pull_lidar_dev.sub_connect("tcp://192.168.1.150:55010")
    pull_lidar_dev.sub_add_url("vlp.image", [-1] * (30600 + 8))


import os
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", '-r', action="store_true")
    # parser.add_argument("--local", '-l', action="store_true")
    parser.add_argument("--path", '-p', type=str, default=None, help="The path of target h5 file.")
    parser.add_argument("--offset", '-o', type=float, required=True,
                        help="The output value of gps_alignment.")
    parser.add_argument("--fps", type=int, default=-1)
    args = parser.parse_args()
    setup_logger("INFO")

    map = LidarMap(lidar_config, args.offset * np.pi / 180)
    detector = Detector()
    v = Visualizer("Detection", detector_config["map_size"], smooth=False, max_size=1000)

    push_detection_dev = MsgDevice()
    build_push_detection_dev(push_detection_dev)

    pull_lidar_dev = MsgDevice()
    build_pull_lidar_dev(pull_lidar_dev)

    if args.fps == -1:
        args.fps = None
    fps_timer = FPSTimer(force_fps=args.fps)

    # parser.add_argument("--path", '-p', required=True, help="The path of target h5 file.")
    # parser.add_argument("--save", '-s', action="store_true")
    # parser.add_argument("--fps", type=int, default=-1)
    # parser.add_argument("--start", type=int, default=0)
    # args = parser.parse_args()

    # assert args.path.endswith(".h5")
    # args.save = args.save and (not os.path.exists(args.path.replace(".h5", ".pkl")))
    # setup_logger("DEBUG")

    use_local_data = False
    if args.path is not None and os.path.exists(args.path):
        from utils import lazy_read_data

        use_local_data = True
        data = lazy_read_data(args.path)
        cnt = 17100
        lidar_dataset = data['lidar_data']
        extra_dataset = data['extra_data']
        logging.info("We are using loaded data {}!".format(args.path))

    from msgdev import PeriodTimer
    pressed_key = -1
    target = None

    periodt = PeriodTimer(0.1)



    try:
        while True:
            with periodt:
                with fps_timer:
                    if use_local_data:
                        lidar_data, extra_data = lidar_dataset[cnt], extra_dataset[cnt]
                        cnt += 1
                        if cnt >= len(lidar_data):
                            break
                    else:
                        tmp_data = pull_lidar_dev.sub_get("vlp.image")
                        lidar_data, extra_data = np.asarray(tmp_data[:30600]), np.asarray(
                            tmp_data[30600:])
                        print(lidar_data.mean())
                    ret = map.update(lidar_data, extra_data)
                    object_d = detector.update(ret)

                    avaliables = detector.availiable_obejct_keys
                    if pressed_key in avaliables:
                        target = avaliables[pressed_key]
                    elif (pressed_key == ord("q")) or (target not in object_d.keys()):
                        target = None
                    if args.render:
                        pressed_key = v.draw(ret["map_n"],
                                             objects=object_d,
                                             target=target or list(avaliables.values()))
                        if pressed_key == ESC:
                            break

                    push_data = build_push_data(detector.object_dict, target)
                    push_detection_dev.pub_set('det.data', push_data)
    except Exception as e:
        pass
    finally:

        # import cv2
        # cv2.destroyWindow("Detection")
        # cv2.destroyAllWindows()
        v.close()
        for _ in range(3):
            push_detection_dev.pub_set("det.data", [-99] * 7)
        time.sleep(5)

        push_detection_dev.close()
        logging.info("Everything Closed!")
