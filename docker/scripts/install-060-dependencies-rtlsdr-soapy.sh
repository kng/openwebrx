#!/usr/bin/env bash
set -euo pipefail
export MAKEFLAGS="-j12"

function cmakebuild() {
  cd $1
  if [[ ! -z "${2:-}" ]]; then
    git checkout $2
  fi
  mkdir build
  cd build
  cmake ..
  make
  make install
  cd ../..
  rm -rf $1
}

cd /tmp

STATIC_PACKAGES="libusb-1.0-0"
BUILD_PACKAGES="git libusb-1.0-0-dev cmake make gcc g++ pkg-config"

if [[ -z ${1:-} ]]; then
  apt-get update
  apt-get -y install --no-install-recommends $STATIC_PACKAGES $BUILD_PACKAGES

  git clone https://github.com/osmocom/rtl-sdr.git
  # latest from master as of 2020-09-04
  cmakebuild rtl-sdr ed0317e6a58c098874ac58b769cf2e609c18d9a5

  git clone https://github.com/pothosware/SoapyRTLSDR.git
  cmakebuild SoapyRTLSDR soapy-rtl-sdr-0.3.1
fi

if [[ -z ${FULL_BUILD:-} || ${1:-} == 'clean' ]]; then
  echo "Cleaning from $0"
  apt-get -y purge --autoremove $BUILD_PACKAGES
  if [[ -z ${FULL_BUILD:-} ]]; then
    apt-get clean
    rm -rf /var/lib/apt/lists/*
  fi
fi
