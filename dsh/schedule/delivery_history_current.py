"""Saved delivery retention and append-order pagination without Session reads."""
from dsh.util_time_instant import four_digit_year_epoch


def append_delivery(task,receipt,bounds):
    history=task['deliveryHistory'];appended=history['records']+[dict(receipt,prompt=task['record']['prompt'])]
    floor=four_digit_year_epoch(receipt['deliveredAt'])['epoch']-bounds['days']*86400000
    retained=[record for record in appended if four_digit_year_epoch(record['deliveredAt'])['epoch']>=floor][-bounds['records']:]
    pruned=len(retained)!=len(appended)
    return dict(lastDelivery=receipt,deliveryHistory=dict(records=retained,earlierRecordsUnavailable=history['earlierRecordsUnavailable'] or pruned,
        earlierRecordsPruned=history['earlierRecordsPruned'] or pruned))


def delivery_history_page(task,request,retention):
    history=task['deliveryHistory'];records=history['records']
    end=len(records) if 'before' not in request else next((index for index,record in enumerate(records) if record['messageId']==request['before']),-1)
    if end==-1:return dict(id=request['id'],code='delivery_cursor_not_found')
    start=max(0,end-request['limit']);page=[dict(record) for record in reversed(records[start:end])]
    result=dict(id=request['id'],records=page,earlierRecordsUnavailable=history['earlierRecordsUnavailable'],earlierRecordsPruned=history['earlierRecordsPruned'],retention=dict(retention))
    if page and start>0:result['nextBefore']=page[-1]['messageId']
    return result


appendDelivery=append_delivery
deliveryHistoryPage=delivery_history_page
