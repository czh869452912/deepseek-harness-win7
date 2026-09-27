import z from '../../reference/vendor/schemastery/src/index.ts'
export async function scenario(id:number) {
 const schema=z.object({name:z.string().required(),age:z.number().min(0).default(18),tags:z.array(z.string()).default([])})
 const standard=schema['~standard']
 return { valid:standard.validate({name:'Alice'}), invalid:standard.validate({name:7,age:-1,tags:[true]}) }
}
