from pathlib import Path
from setuptools import setup

name = 'robot_reliability_testbench'
data = [('share/ament_index/resource_index/packages', ['resource/' + name]),
        ('share/' + name, ['package.xml'])]
for directory in ['launch', 'config', 'models']:
    folders = {}
    for path in Path(directory).rglob('*'):
        if path.is_file():
            folders.setdefault(str(path.parent), []).append(str(path))
    data.extend(('share/' + name + '/' + folder, files) for folder, files in folders.items())
setup(name=name, version='0.2.0', packages=['reliability_testbench'],
      data_files=data, install_requires=['setuptools', 'numpy', 'mujoco==3.16.0', 'psutil==5.9.8'],
      zip_safe=False, maintainer='Hafiz', maintainer_email='hafiz@example.com',
      tests_require=['pytest'],
      description='Software-only ROS 2 Panda reliability testbench', license='Apache-2.0',
      entry_points={'console_scripts': [
          'endurance = reliability_testbench.endurance:main',
          'simulator = reliability_testbench.simulator_node:main',
          'task_server = reliability_testbench.task_server:main',
          'fault_boundary = reliability_testbench.fault_boundary:main',
          'health_monitor = reliability_testbench.health_monitor:main',
          'milestone_d = reliability_testbench.fault_demo:main',
          'fault_replay = reliability_testbench.fault_bags:main',
          'fault_bag_analyze = reliability_testbench.fault_bags:analysis_main',
          'milestone_b = reliability_testbench.milestone_b_demo:main',
          'bag_analyze = reliability_testbench.bag_analysis:main',
          'replay_session = reliability_testbench.replay:main',
          'milestone_c = reliability_testbench.bag_workflow:main',
          'milestone_a = reliability_testbench.demo:main']})
