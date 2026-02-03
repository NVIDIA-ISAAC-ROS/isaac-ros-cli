# Based on https://github.com/stereolabs/zed-docker

# Extract ubuntu release year from /etc/lsb-release
# Expects "/etc/lsb-release" to contain a line similar to "DISTRIB_RELEASE=20.04"
export UBUNTU_RELEASE_YEAR="$(grep -o -P 'DISTRIB_RELEASE=.{0,2}' /etc/lsb-release | cut -d= -f2)"
export ZED_SDK_MAJOR=5 ZED_SDK_MINOR=1

# Extract cuda major and minor version from nvcc --version
# Expects "nvcc --version" to contain a line similar to "release 11.8"
export CUDA_MAJOR="$(nvcc --version | grep -o -P ' release .{0,4}' | cut -d. -f1 | cut -d ' ' -f3)"
export CUDA_MINOR="$(nvcc --version | grep -o -P ' release .{0,4}' | cut -d. -f2)"


# Download dependencies for zed SDK installation RUN file
sudo apt-get update -y || true
sudo apt-get install --no-install-recommends lsb-release wget less udev sudo zstd build-essential cmake libpng-dev libgomp1 -y

ZED_SDK_URL="https://download.stereolabs.com/zedsdk/${ZED_SDK_MAJOR}.${ZED_SDK_MINOR}/cu${CUDA_MAJOR}/ubuntu${UBUNTU_RELEASE_YEAR}"
echo "Downloading SDK from ${ZED_SDK_URL}"

# Download zed SDK installation RUN file to /tmp directory
cd /tmp
wget -O ZED_SDK_Linux_Ubuntu${UBUNTU_RELEASE_YEAR}.run ${ZED_SDK_URL}
chmod +x ZED_SDK_Linux_Ubuntu${UBUNTU_RELEASE_YEAR}.run ; 

echo "Installing ZED SDK"
sudo ./ZED_SDK_Linux_Ubuntu${UBUNTU_RELEASE_YEAR}.run -- silent skip_od_module skip_python skip_cuda

# Cleanup
rm ZED_SDK_Linux_Ubuntu${UBUNTU_RELEASE_YEAR}.run
sudo rm -rf /var/lib/apt/lists/*
