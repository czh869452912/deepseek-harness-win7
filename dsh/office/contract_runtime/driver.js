// Closed platform queries only. Original SDK validation functions own policy.
let current;
function pathInfo(value) {
  if(!Object.hasOwn(current.paths,value))throw Error('Unprepared Office path query.');
  return current.paths[value];
}
function isAbsolute(value) {return pathInfo(value).absolute;}
function resolve(value) {return pathInfo(value).resolved;}
function extname(value) {return pathInfo(value).extension;}
function relative(left,right) {
  if(left!==current.resolvedOutput||right!==current.resolvedInput)throw Error('Unprepared Office relative path query.');
  return current.within;
}
function systemFontDirectories() {return current.systemRoots;}
function defaultFontMetadataCacheDirectory() {return current.cacheDirectory;}
globalThis.__receive=()=>{};
globalThis.__drive=async()=>{
  const rows=[];
  for(current of __request.operations){
    for(const special of current.specials){
      let parent=current;for(const key of special.path.slice(0,-1))parent=parent[key];
      parent[special.path.at(-1)]=special.kind==='nan'?NaN:special.kind==='positive'?Infinity:special.kind==='negative'?-Infinity:undefined;
    }
    try{
      const value=current.kind==='options'?resolveOptions(current.value):current.kind==='images'?resolveImageRender(current.value):resolveConversion(current.value,current.kind);
      rows.push({ok:true,value});
    }catch(error){rows.push({ok:false,name:error.name,message:error.message,...error.code===undefined?{}:{code:error.code}});}
  }
  __emit(JSON.stringify({type:'terminal',result:rows}));
};
