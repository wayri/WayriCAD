"""Offline display shading on saved support; solver values remain untouched."""
from __future__ import annotations


def field_palette(name):
    """Use the same 256-entry lookup table as the native Matplotlib viewport."""
    from matplotlib import colormaps
    return colormaps[name]([i / 255 for i in range(256)], bytes=True).tolist()


# Pure pixel functions also run under Node for reference/pixel regression checks.
# Callers keep one current texture, then transform it for pan, zoom and orbit.
FIELD_SCRIPT = r'''
const SavedField = (() => {
 'use strict';
 const known = Number.isFinite;
 function raster(bounds, maxSide) {
  if(!Array.isArray(bounds)||bounds.length!==4||!bounds.every(known))return null;
  const dx=bounds[2]-bounds[0],dy=bounds[3]-bounds[1];
  if(!(dx>0&&dy>0))return null;
  const size=Math.max(2,Math.min(2048,Math.floor(maxSide)||1024));
  const scale=size/Math.max(dx,dy),width=Math.max(2,Math.ceil(dx*scale)),height=Math.max(2,Math.ceil(dy*scale));
  return {bounds:bounds.slice(),width,height,pixels:new Uint8ClampedArray(width*height*4)};
 }
 function colour(value,palette,limits) {
  if(!known(value)||!Array.isArray(limits)||limits.length!==2||!limits.every(known)||limits[1]<limits[0])return null;
  let t=limits[1]===limits[0]?0:(value-limits[0])/(limits[1]-limits[0]);
  t=Math.max(0,Math.min(1,t));
  return palette[Math.min(palette.length-1,Math.floor(t*palette.length))]||null;
 }
 function position(image,p) {
  return [(p[0]-image.bounds[0])*image.width/(image.bounds[2]-image.bounds[0]),
          (p[1]-image.bounds[1])*image.height/(image.bounds[3]-image.bounds[1])];
 }
 function triangle(image,vertices,colours) {
  if(!vertices.every(p=>p&&p.length>=2&&known(p[0])&&known(p[1]))||!colours.every(c=>c&&c.length>=3))return;
  const [a,b,c]=vertices.map(p=>position(image,p));
  const denominator=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);
  if(!known(denominator)||Math.abs(denominator)<1e-12)return;
  const xmin=Math.max(0,Math.floor(Math.min(a[0],b[0],c[0]))),xmax=Math.min(image.width-1,Math.ceil(Math.max(a[0],b[0],c[0])));
  const ymin=Math.max(0,Math.floor(Math.min(a[1],b[1],c[1]))),ymax=Math.min(image.height-1,Math.ceil(Math.max(a[1],b[1],c[1])));
  for(let y=ymin;y<=ymax;y++)for(let x=xmin;x<=xmax;x++){
   const px=x+.5,py=y+.5;
   const u=((b[1]-c[1])*(px-c[0])+(c[0]-b[0])*(py-c[1]))/denominator;
   const v=((c[1]-a[1])*(px-c[0])+(a[0]-c[0])*(py-c[1]))/denominator,w=1-u-v;
   if(u < -1e-8||v < -1e-8||w < -1e-8)continue;
   const offset=4*(y*image.width+x);
   for(let channel=0;channel<3;channel++)image.pixels[offset+channel]=u*colours[0][channel]+v*colours[1][channel]+w*colours[2][channel];
   image.pixels[offset+3]=255;
  }
 }
 function rectangle(image,box,rgba) {
  if(!rgba)return;
  const a=position(image,box.slice(0,2)),b=position(image,box.slice(2));
  for(let y=Math.max(0,Math.ceil(a[1]-.5));y<Math.min(image.height,Math.ceil(b[1]-.5));y++)
   for(let x=Math.max(0,Math.ceil(a[0]-.5));x<Math.min(image.width,Math.ceil(b[0]-.5));x++){
    const offset=4*(y*image.width+x);
    image.pixels.set([rgba[0],rgba[1],rgba[2],255],offset);
   }
 }
 function mesh(surface,palette,limits,style='smooth',maxSide=1024) {
  const image=raster(surface.bounds,maxSide);if(!image)return null;
  const points=surface.points||[],values=surface.values||[];
  for(const face of surface.triangles||[]){
   if(face.length!==3||!face.every(i=>Number.isInteger(i)&&i>=0&&i<points.length))continue;
   const colours=face.map(i=>colour(values[i],palette,limits));
   if(!colours.every(Boolean))continue;
   triangle(image,face.map(i=>points[i]),style==='cells'?[colours[0],colours[0],colours[0]]:colours);
  }
  return image;
 }
 function increasing(a){return Array.isArray(a)&&a.length>0&&a.every((v,i)=>known(v)&&(!i||v>a[i-1]));}
 function grid(field,palette,limits,style='smooth',maxSide=1024) {
  if(!field||field.status==='unavailable')return null;
  const xs=field.x_centers_mm||[],ys=field.y_centers_mm||[],values=field.values_c||[];
  if(!increasing(xs)||!increasing(ys)||values.length!==ys.length||!values.every(row=>Array.isArray(row)&&row.length===xs.length))return null;
  const xe=field.x_edges_mm,ye=field.y_edges_mm;
  const cells=field.value_location==='finite_volume_cell'&&increasing(xe)&&increasing(ye)&&xe.length===xs.length+1&&ye.length===ys.length+1;
  const bounds=cells?[xe[0],ye[0],xe.at(-1),ye.at(-1)]:[xs[0],ys[0],xs.at(-1),ys.at(-1)];
  const image=raster(bounds,maxSide);if(!image)return null;let drawn=false;
  if(cells)for(let j=0;j<ys.length;j++)for(let i=0;i<xs.length;i++){
   const rgba=colour(values[j][i],palette,limits);if(!rgba)continue;
   rectangle(image,[xe[i],ye[j],xe[i+1],ye[j+1]],rgba);drawn=true;
  }
  for(let j=0;j<ys.length-1;j++)for(let i=0;i<xs.length-1;i++){
   const colours=[values[j][i],values[j][i+1],values[j+1][i+1],values[j+1][i]].map(v=>colour(v,palette,limits));
   if(!colours.every(Boolean))continue;
   const corners=[[xs[i],ys[j]],[xs[i+1],ys[j]],[xs[i+1],ys[j+1]],[xs[i],ys[j+1]]];
   if(style==='cells'&&!cells){rectangle(image,[xs[i],ys[j],xs[i+1],ys[j+1]],colours[0]);drawn=true;}
   else if(style!=='cells'){
    triangle(image,[corners[0],corners[1],corners[2]],[colours[0],colours[1],colours[2]]);
    triangle(image,[corners[0],corners[2],corners[3]],[colours[0],colours[2],colours[3]]);drawn=true;
   }
  }
  return drawn?image:null;
 }
 function canvas(image){
  if(!image)return null;const result=document.createElement('canvas');result.width=image.width;result.height=image.height;
  const ctx=result.getContext('2d'),pixels=ctx.createImageData(image.width,image.height);pixels.data.set(image.pixels);ctx.putImageData(pixels,0,0);return result;
 }
 return {mesh,grid,canvas,colour};
})();
'''
