from setuptools import find_packages, setup

package_name = "wuliusai_stepper_controller"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", ["config/stepper_controller.yaml"]),
        ("share/" + package_name + "/launch", ["launch/stepper_controller.launch.py"]),
    ],
    install_requires=["setuptools", "pyserial"],
    zip_safe=True,
    entry_points={"console_scripts": [
        "stepper_controller = wuliusai_stepper_controller.node:main",
        "stepper_serial_test = wuliusai_stepper_controller.serial_test:main",
    ]},
)
