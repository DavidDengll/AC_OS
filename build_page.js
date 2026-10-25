// Build markmap root JSON + HTML page from markdown, all in one, lossless UTF-8
const fs = require('fs');
const path = require('path');

// markmap-lib is installed in %TEMP%\node_modules
const markmapLib = require(path.join(process.env.TEMP, 'node_modules', 'markmap-lib'));
const transformer = new markmapLib.Transformer();

const md = fs.readFileSync('D:\\DSH-Workspace\\动植物体结构层次_思维导图.md', 'utf8');
const { root } = transformer.transform(md);

fs.writeFileSync('D:\\DSH-Workspace\\mm_root.json', JSON.stringify(root), 'utf8');

const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  html,body{margin:0;padding:0;}
  #mindmap{width:1400px;height:1000px;}
  .markmap-node text{font-size:16px;}
</style>
</head>
<body>
<svg id="mindmap"></svg>
<script src="https://cdn.jsdelivr.net/npm/d3@7"><\/script>
<script src="https://cdn.jsdelivr.net/npm/markmap-view@0.18"><\/script>
<script>
const root = ${JSON.stringify(root)};
window.mm = markmap.Markmap.create(document.querySelector('#mindmap'), {duration:0, spacingVertical:8, paddingX:16, maxWidth:280}, root);
</script>
</body>
</html>`;

fs.writeFileSync('D:\\DSH-Workspace\\mm_page.html', html, 'utf8');
console.log('root nodes ok, html chars:', html.length);
console.log('title check:', root.children[0].content.slice(0, 30));
