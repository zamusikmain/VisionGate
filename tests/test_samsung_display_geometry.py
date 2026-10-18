import cv2
import numpy as np
from backend.gate.samsung_display_geometry import display_boundaries,framed_gallery_evidence

def line(text,x,y,w=120):return dict(text=text,words=[dict(x=x,y=y,width=w,height=14)])
def test_geometry_is_only_a_candidate_and_scales_with_the_image():
    image=np.full((800,600,3),220,np.uint8);cv2.rectangle(image,(100,40),(500,760),(15,15,15),16)
    a=display_boundaries(image);b=display_boundaries(cv2.resize(image,None,fx=2,fy=2))
    assert a and b and all(x['semantic_status']=='CANDIDATE_ONLY' for x in a)
    assert framed_gallery_evidence(dict(reads=[]),a) is None
def test_two_controls_must_be_inside_same_foreground_frame():
    frames=[dict(polygon=[[50,20],[550,20],[550,780],[50,780]])]
    ocr=dict(reads=[dict(lines=[line('+123 456 789',100,50),line('3 photos',110,85)])])
    assert framed_gallery_evidence(ocr,frames)['code']=='FOREGROUND_DISPLAY_GALLERY'
    assert framed_gallery_evidence(ocr,[]) is None
    assert framed_gallery_evidence(dict(reads=[dict(lines=[line('+123 456 789',100,50)])]),frames) is None
    assert framed_gallery_evidence(dict(reads=[dict(lines=[line('+123 456 789',0,50),line('3 photos',110,85)])]),frames) is None
def test_reply_requires_bottom_position_and_contact_header():
    frames=[dict(polygon=[[50,20],[550,20],[550,780],[50,780]])]
    assert framed_gallery_evidence(dict(reads=[dict(lines=[line('+123 456 789',100,50),line('Reply',110,710)])]),frames)
    assert framed_gallery_evidence(dict(reads=[dict(lines=[line('+123 456 789',100,50),line('Reply',110,200)])]),frames) is None
    assert framed_gallery_evidence(dict(reads=[dict(lines=[line('Reply',110,710)])]),frames) is None
def test_automatic_ui_bands_map_back_without_manual_region(monkeypatch):
    from backend.gate.samsung_display_geometry import read_framed_ui
    from backend.gate import samsung_screen
    calls=[]
    def read(image,cache_dir):
        calls.append(image.shape)
        return dict(reads=[dict(lines=[line('+123 456 789' if len(calls)==1 else 'Reply',40,30)])])
    monkeypatch.setattr(samsung_screen,'read_screen_ui',read)
    frames=[dict(polygon=[[50,20],[550,20],[550,780],[50,780]])]
    result=read_framed_ui(np.full((800,600,3),200,np.uint8),frames)
    assert result['coordinate_space']=='original' and result['manual_region'] is False
    assert len(calls)==2 and framed_gallery_evidence(result,frames)
