import fs from 'node:fs';import path from 'node:path';
const root=process.cwd(),manifest=JSON.parse(fs.readFileSync('cloud/assets-manifest.json'));let removed=0;for(const f of manifest.files){const file=path.join(root,'dist/client',f.path);if(fs.existsSync(file)){fs.unlinkSync(file);removed++}}console.log(JSON.stringify({assetsStoredInR2:manifest.files.length,removedFromDeployment:removed}));
