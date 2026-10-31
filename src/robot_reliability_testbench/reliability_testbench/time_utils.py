"""ROS timestamp conversion, independent of physics and fault configuration."""
from builtin_interfaces.msg import Time


def sim_stamp(seconds):
    ns = round(seconds * 1e9)
    return Time(sec=ns // 10**9, nanosec=ns % 10**9)
