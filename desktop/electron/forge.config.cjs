const path = require('node:path')

module.exports = {
  packagerConfig: {
    asar: true,
    executableName: 'sprite-studio',
    extraResource: [
      path.resolve(__dirname, 'resources/backend'),
      path.resolve(__dirname, 'resources/web-dist'),
    ],
  },
  makers: [
    {
      name: '@electron-forge/maker-squirrel',
      config: {
        name: 'sprite_studio',
      },
    },
    {
      name: '@electron-forge/maker-zip',
      platforms: ['win32', 'darwin', 'linux'],
    },
  ],
}
