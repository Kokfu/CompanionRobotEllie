from PIL import Image
from fall_prediction import Fall_prediction

img1 = Image.open("Images/fall_img_22.jpg")
img2 = Image.open("Images/fall_img_23.jpg")
img3 = Image.open("Images/fall_img_24.jpg")

response = Fall_prediction(img1, img2, img3)

if response:
    print("There is", response['category'])
    print("Confidence :", response['confidence'])
    print("Angle : ", response['angle'])
    print("Keypoint_corr :", response['keypoint_corr'])
else:
     print("There is no fall detetcion...")
