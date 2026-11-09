"use strict";

/** Linux release payload: shell in ASAR, native backend beside the archive. */
module.exports = {
  appId: "org.anki_generator.AnkiGenerator",
  productName: "Anki Generator",
  executableName: "anki-generator",
  artifactName: "Anki-Generator-${version}-${arch}.${ext}",
  directories: { output: "../dist/desktop", buildResources: "build" },
  files: [
    "*.cjs",
    "*.html",
    "*.js",
    "*.css",
    "lib/**/*",
    "package.json",
    "!electron-builder.cjs",
  ],
  extraResources: [
    { from: "../build/desktop/backend/anki-generator-backend", to: "backend" },
    { from: "build/icon.png", to: "icon.png" },
  ],
  asar: true,
  electronFuses: {
    runAsNode: false,
    enableNodeOptionsEnvironmentVariable: false,
    enableNodeCliInspectArguments: true,
  },
  npmRebuild: false,
  allowMissingDependencies: false,
  publish: null,
  linux: {
    target: ["AppImage"],
    icon: "build/icons",
    category: "Education",
    synopsis: "Generate evidence-backed university flashcards",
    maintainer: "Anki Generator contributors",
    vendor: "Anki Generator contributors",
    syncDesktopName: true,
    desktop: {
      entry: {
        Name: "Anki Generator",
        Comment: "Turn university sources into reviewed Anki flashcards",
        StartupWMClass: "org.anki_generator.AnkiGenerator",
        Keywords: "Anki;Flashcards;University;Study;",
        Terminal: "false",
      },
    },
  },
};
