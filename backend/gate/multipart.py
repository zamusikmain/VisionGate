"""Strict single-photo multipart parsing with deterministic temporary-file cleanup.

The framework parser currently accepts an unfinished multipart stream and can
leave a part not owned by the returned FormData. Keep OpenAPI's File schema while
enforcing completion and closing every allocated spool on failure.
"""
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.formparsers import MultiPartParser, MultiPartException
from starlette.exceptions import HTTPException

class CompleteMultipartParser(MultiPartParser):
    def on_end(self):
        self.complete=True

    async def parse(self):
        self.complete=False
        try:
            form=await super().parse()
            if not self.complete:
                raise MultiPartException('Incomplete multipart upload')
            return form
        except BaseException:
            for file in self._files_to_close_on_error:
                file.close()
            raise

class PhotoRequest(Request):
    upload_max_files = 1
    async def _get_form(self, *, max_files=1000, max_fields=1000, max_part_size=1024*1024):
        if self._form is None:
            media=self.headers.get('content-type','').split(';',1)[0].strip().lower()
            if media!='multipart/form-data':raise HTTPException(422,'INVALID_REQUEST')
            parser=CompleteMultipartParser(self.headers,self.stream(),max_files=self.upload_max_files,max_fields=0,max_part_size=max_part_size)
            try:self._form=await parser.parse()
            except MultiPartException as exc:raise HTTPException(422,'INVALID_REQUEST') from exc
        return self._form

class PhotoUploadRoute(APIRoute):
    request_class = PhotoRequest
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def handle(request):
            return await handler(self.request_class(request.scope,request.receive))
        return handle


class CaseRequest(PhotoRequest):
    upload_max_files = 2


class CaseUploadRoute(PhotoUploadRoute):
    request_class = CaseRequest
