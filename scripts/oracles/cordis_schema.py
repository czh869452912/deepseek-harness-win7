from dsh.cordis.schema import Schema
async def scenario(number):
    schema=Schema.object({'name':Schema.string().required(),'age':Schema.number().min(0).default(18),'tags':Schema.array(Schema.string()).default([])})
    standard=schema['~standard']
    return {'valid':standard['validate']({'name':'Alice'}),'invalid':standard['validate']({'name':7,'age':-1,'tags':[True]})}
