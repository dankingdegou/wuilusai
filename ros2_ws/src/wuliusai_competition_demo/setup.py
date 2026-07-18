from glob import glob
from setuptools import find_packages, setup

package_name = "wuliusai_competition_demo"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools", "numpy", "PyYAML"],
    zip_safe=True,
    entry_points={"console_scripts": [
        "competition_demo = wuliusai_competition_demo.node:main",
        "competition_calibrate_field = wuliusai_competition_demo.calibrate_field:main",
        "competition_send_task = wuliusai_competition_demo.send_task:main",
    ]},
)
