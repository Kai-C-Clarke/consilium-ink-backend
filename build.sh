#!/usr/bin/env bash
# Build script for Render.com deployment
# Installs FluidSynth, abcmidi, lame, and FluidR3 SoundFont

set -e

echo "Installing system audio dependencies..."
apt-get update -qq
apt-get install -y -qq \
  fluidsynth \
  fluid-soundfont-gm \
  abcmidi \
  lame

echo "Verifying installations..."
fluidsynth --version
abc2midi 2>&1 | head -1
lame --version | head -1

echo "Available SoundFonts:"
ls /usr/share/sounds/sf2/

echo "Build complete."
