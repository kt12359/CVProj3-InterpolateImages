import cv2
import sys
import numpy as np
import pickle
import numpy as np
import os
import math

BLUR_OCC = 3


def readFlowFile(file):
    '''
    credit: this function code is obtained from: https://github.com/Johswald/flow-code-python
    '''
    TAG_FLOAT = 202021.25
    assert type(file) is str, "file is not str %r" % str(file)
    assert os.path.isfile(file) is True, "file does not exist %r" % str(file)
    assert file[-4:] == '.flo', "file ending is not .flo %r" % file[-4:]
    f = open(file,'rb')
    flo_number = np.fromfile(f, np.float32, count=1)[0]
    assert flo_number == TAG_FLOAT, 'Flow number %r incorrect. Invalid .flo file' % flo_number
    w = np.fromfile(f, np.int32, count=1)[0]
    h = np.fromfile(f, np.int32, count=1)[0]
    data = np.fromfile(f, np.float32, count=2*w*h)
    # Reshape data into 3D array (columns, rows, bands)
    flow = np.resize(data, (int(h), int(w), 2))
    f.close()
    return flow


def find_holes(flow):
    '''
    Find a mask of holes in a given flow matrix
    Determine it is a hole if a vector length is too long: >10^9, of it contains NAN, of INF
    :param flow: an dense optical flow matrix of shape [h,w,2], containing a vector [ux,uy] for each pixel
    :return: a mask annotated 0=hole, 1=no hole
    '''
    height, width = flow.shape[:2]
    holes = np.array([[0]* width]*height)
    for y in range(0, height):
        for x in range(0, width):
            if flow[y][x][0] > 1e9 or flow[y][x][1] > 1e9 or math.isnan(flow[y][x][0]) or math.isnan(flow[y][x][1]) or np.isinf(flow[y][x][0]) or np.isinf(flow[y][x][1]):
                holes[y][x] = 0
            else:
                holes[y][x] = 1
    return holes

def holefill(flow, holes):
    '''
    fill holes in order: row then column, until fill in all the holes in the flow
    :param flow: matrix of dense optical flow, it has shape [h,w,2]
    :param holes: a binary mask that annotate the location of a hole, 0=hole, 1=no hole
    :return: flow: updated flow
    '''
    h,w,_ = flow.shape
    has_hole=1
    while has_hole==1:
        has_hole = 0
        # ===== loop all pixel in x, then in y
        for y in range(0, w, 1): #columns
            for x in range(0, h, 1): #rows
                u = []
                v = []
                # If current index is a hole
                if holes[x][y] == 0:
                    count = 0
                    for j in range(x - 1, x + 2, 1): #rows
                        for i in range(y - 1, y + 2, 1): #columns
                            if i >= 0 and i < w and j >= 0 and j < h:
                                if holes[j][i] != 0:
                                    u.append(flow[j][i][0])
                                    v.append(flow[j][i][1])
                    if len(u) == 0 or len(v) == 0:
                        has_hole = 1
                    else:
                        ux = np.sum(u)/len(u)
                        uy = np.sum(v)/len(v)
                        flow[x][y][0] = ux
                        flow[x][y][1] = uy
                        holes[x][y] = 1
    return flow

def bilinearInterp(frame, fx, fy):
   pixel = np.array([0,0,0], np.float32)
   a = fx-int(fx)
   b = fy-int(fy)
   x = np.clip(int(fx), 1, frame.shape[1]-2)
   y = np.clip(int(fy), 1, frame.shape[0]-2)
   #Calculate weights for bilinear interpolation.
   weight1 = (1-a)*(1-b)
   weight2 = a*(1-b)
   weight3 = b*a
   weight4 = (1-a)*b
   # Apply bilinear interpolation to each channel of image.
   for color in range(0, 3):
       pixel[color] = weight1 * frame[y][x][color] + weight2 * frame[y][x+1][color] + weight3 * frame[y+1][x+1][color] + weight4 * frame[y+1][x][color]
   return pixel

def bilinearInterpOcclusion(frame, fx, fy):
   pixel = np.array([0,0,0], np.float32)
   a = fx-int(fx)
   b = fy-int(fy)
   x = np.clip(int(fx), 1, frame.shape[1]-2)
   y = np.clip(int(fy), 1, frame.shape[0]-2)
   #Calculate weights for bilinear interpolation.
   weight1 = (1-a)*(1-b)
   weight2 = a*(1-b)
   weight3 = b*a
   weight4 = (1-a)*b
   # Apply bilinear interpolation to each channel of image.
   pixel = weight1 * frame[y][x] + weight2 * frame[y][x+1] + weight3 * frame[y+1][x+1] + weight4 * frame[y+1][x]
   return pixel

def occlusions(flow0, frame0, frame1):
    '''
    Follow the step 3 in 3.3.2 of
    Simon Baker, Daniel Scharstein, J. P. Lewis, Stefan Roth, Michael J. Black, and Richard Szeliski. A Database and Evaluation Methodology
    for Optical Flow, International Journal of Computer Vision, 92(1):1-31, March 2011.
    :param flow0: dense optical flow
    :param frame0: input image frame 0
    :param frame1: input image frame 1
    :return:
    '''
    height,width,_ = flow0.shape
    occ0 = np.zeros([height,width],dtype=np.float32)
    occ1 = np.zeros([height,width],dtype=np.float32)

    # ==================================================
    # ===== step 4/ warp flow field to target frame
    # ==================================================
    flow1 = interpflow(flow0, frame0, frame1, 1.0)
    pickle.dump(flow1, open('flow1.step4.data', 'wb'))
    # ====== score
    flow1 = pickle.load(open('flow1.step4.data', 'rb'))
    flow1_step4 = pickle.load(open('flow1.step4.sample', 'rb'))
    diff = np.sum(np.abs(flow1-flow1_step4))
    print('flow1_step4',diff)

    # ==================================================
    # ===== main part of step 5
    # ==================================================
    for y in range(0, height):
        for x in range(0, width):
            total = 0
            occluded = 0
            for yy in np.arange(-0.5, 0.51, 0.5):
                for xx in np.arange(-0.5, 0.51, 0.5):
                    nx = np.int32(x + flow0[y][x][0] + xx + 0.5)
                    ny = np.int32(y + flow0[y][x][1] + yy + 0.5)
                    if ny < height and nx < width and ny >= 0 and nx >= 0:
                        if np.sum(abs(flow1[ny][nx] - flow0[y][x])) >= 0.5:
                            occluded += 1
                    else:
                        occluded += 1
                    total += 1
            if occluded/total >= 0.6: # > 0.6 best so far, testing 0.65
                occ0[y][x] = 1
    for y in range(0, height):
        for x in range(0, width):
            if flow1[y][x][0] >= 1e10 or flow1[y][x][1] >= 1e10:
                occ1[y][x] = 1
    return occ0,occ1

def interpflow(flow, frame0, frame1, t):
    '''
    Forward warping flow (from frame0 to frame1) to a position t in the middle of the 2 frames
    Follow the algorithm (1) described in 3.3.2 of
    Simon Baker, Daniel Scharstein, J. P. Lewis, Stefan Roth, Michael J. Black, and Richard Szeliski. A Database and Evaluation Methodology
    for Optical Flow, International Journal of Computer Vision, 92(1):1-31, March 2011.

    :param flow: dense optical flow from frame0 to frame1
    :param frame0: input image frame 0
    :param frame1: input image frame 1
    :param t: the intermiddite position in the middle of the 2 input frames
    :return: a warped flow
    '''
    height, width = frame0.shape[:2]
    frame0 = frame0.astype(np.float32)
    iflow = np.full_like(flow0, 1e10)
    confidence = [[1e10 for i in range(width)] for j in range(height)] 

    for y in range(0,height):
        for x in range(0, width):
            for yy in np.arange(-0.5,0.51,0.5):
                for xx in np.arange(-0.5,0.51,0.5): 
                    nx = np.int32(x + t*flow[y][x][0] + xx + 0.5)
                    ny = np.int32(y + t*flow[y][x][1] + yy + 0.5)
                    clipped_x = np.clip(x+xx+flow[y][x][0], 0, width-1)
                    clipped_y = np.clip(y+yy+flow[y][x][1], 0, height-1)
                    if ny < height and nx < width and ny >= 0 and nx >= 0:
                        p1 = bilinearInterp(frame1.astype(np.float32), clipped_x, clipped_y)
                        conf = np.sum(abs(p1 - frame0[y][x]))
                        if conf < confidence[ny][nx]:
                            confidence[ny][nx] = conf
                            iflow[ny][nx][0] = flow[y][x][0]
                            iflow[ny][nx][1] = flow[y][x][1]
    return iflow

def warpimages(iflow, frame0, frame1, occ0, occ1, t):
    '''
    Compute the colors of the interpolated pixels by inverse-warping frame 0 and frame 1 to the postion t based on the
    forwarded-warped flow iflow at t
    Follow the algorithm (4) described in 3.3.2 of
    Simon Baker, Daniel Scharstein, J. P. Lewis, Stefan Roth, Michael J. Black, and Richard Szeliski. A Database and Evaluation Methodology
     for Optical Flow, International Journal of Computer Vision, 92(1):1-31, March 2011.

    :param iflow: forwarded-warped (from flow0) at position t
    :param frame0: input image frame 0
    :param frame1: input image frame 1
    :param occ0: occlusion mask of frame 0
    :param occ1: occlusion mask of frame 1
    :param t: interpolated position t
    :return: interpolated image at position t in the middle of the 2 input frames
    '''

    iframe = np.zeros_like(frame0).astype(np.float32)
    height, width = frame0.shape[:2]
    for y in range(0, height):
        for x in range(0, width):
            x0 = np.float32(x) - t * iflow[y][x][0].astype(np.float32)
            y0 = np.float32(y) - t * iflow[y][x][1].astype(np.float32)
            x1 = np.float32(x) + (1-t) * iflow[y][x][0].astype(np.float32)
            y1 = np.float32(y) + (1-t) * iflow[y][x][1].astype(np.float32)
            if x0 < width and y0 < height and x0 >= 0 and y0 >= 0 and x1 < width and y1 < height and x1 >= 0 and y1 >= 0:
                pixel0 = bilinearInterp(frame0.astype(np.float32), x0, y0)
                pixel1 = bilinearInterp(frame1.astype(np.float32), x1, y1)

                o_pixel0 = bilinearInterpOcclusion(occ0.astype(np.float32), x0, y0)#occ0[y0][x0]  # if pixel in occ0 is not in frame1
                o_pixel1 = bilinearInterpOcclusion(occ1.astype(np.float32), x1, y1)#occ1[y1][x1]
                oc0 = np.int32(o_pixel0+0.5)
                oc1 = np.int32(o_pixel1+0.5)

                if  oc0==0 and oc1==0: 
                    w0= 1-t          #when t is 1  w0 is 0
                    w1= t            # and w 0 is 1              
                elif oc0 > oc1:
                    w0 = 0
                    w1 = 1
                else:
                    w1= 0
                    w0= 1 # we blending
                iframe[y,x,:] = np.int32(w0*pixel0 + w1*pixel1+0.5)
            else:
                iframe[y,x,:] = frame1[y,x,:]
    return iframe

def blur(im):
    '''
    blur using a gaussian kernel [5,5] using opencv function: cv2.GaussianBlur, sigma=0
    :param im:
    :return updated im:
    '''
    im = cv2.GaussianBlur(im, (5,5), 0)
    return im


def internp(frame0, frame1, t=0.5, flow0=None):
    '''
    :param frame0: beggining frame
    :param frame1: ending frame
    :return frame_t: an interpolated frame at time t
    '''
    print('==============================')
    print('===== interpolate an intermediate frame at t=',str(t))
    print('==============================')

    # ==================================================
    # ===== 1/ find the optical flow between the two given images: from frame0 to frame1,
    #  if there is no given flow0, run opencv function to extract it
    # ==================================================
    if flow0 is None:
        i1 = cv2.cvtColor(frame0, cv2.COLOR_BGR2GRAY)
        i2 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        flow0 = cv2.calcOpticalFlowFarneback(i1, i2, None, 0.5, 3, 15, 3, 5, 1.2, 0)

    # ==================================================
    # ===== 2/ find holes in the flow
    # ==================================================
    holes0 = find_holes(flow0)
    pickle.dump(holes0,open('holes0.step2.data','wb'))  # save your intermediate result
    # ====== score
    holes0       = pickle.load(open('holes0.step2.data','rb')) # load your intermediate result
    holes0_step2 = pickle.load(open('holes0.step2.sample','rb')) # load sample result
    diff = np.sum(np.abs(holes0-holes0_step2))
    print('holes0_step2',diff)

    # ==================================================
    # ===== 3/ fill in any hole using an outside-in strategy
    # ==================================================
    flow0 = holefill(flow0,holes0)
    pickle.dump(flow0, open('flow0.step3.data', 'wb')) # save your intermediate result
    # ====== score
    flow0       = pickle.load(open('flow0.step3.data', 'rb')) # load your intermediate result
    flow0_step3 = pickle.load(open('flow0.step3.sample', 'rb')) # load sample result
    diff = np.sum(np.abs(flow0-flow0_step3))
    print('flow0_step3',diff)

    # ==================================================
    # ===== 5/ estimate occlusion mask
    # ==================================================
    occ0, occ1 = occlusions(flow0,frame0,frame1)
    pickle.dump(occ0, open('occ0.step5.data', 'wb')) # save your intermediate result
    pickle.dump(occ1, open('occ1.step5.data', 'wb')) # save your intermediate result
    # ===== score
    occ0        = pickle.load(open('occ0.step5.data', 'rb')) # load your intermediate result
    occ1        = pickle.load(open('occ1.step5.data', 'rb')) # load your intermediate result
    occ0_step5  = pickle.load(open('occ0.step5.sample', 'rb')) # load sample result
    occ1_step5  = pickle.load(open('occ1.step5.sample', 'rb')) # load sample result
    diff = np.sum(np.abs(occ0_step5 - occ0))
    print('occ0_step5',diff)
    diff = np.sum(np.abs(occ1_step5 - occ1))
    print('occ1_step5',diff)

    # ==================================================
    # ===== step 6/ blur occlusion mask
    # ==================================================
    for iblur in range(0,BLUR_OCC):
        occ0 = blur(occ0)
        occ1 = blur(occ1)
    pickle.dump(occ0, open('occ0.step6.data', 'wb')) # save your intermediate result
    pickle.dump(occ1, open('occ1.step6.data', 'wb')) # save your intermediate result
    # ===== score
    occ0        = pickle.load(open('occ0.step6.data', 'rb')) # load your intermediate result
    occ1        = pickle.load(open('occ1.step6.data', 'rb')) # load your intermediate result
    occ0_step6  = pickle.load(open('occ0.step6.sample', 'rb')) # load sample result
    occ1_step6  = pickle.load(open('occ1.step6.sample', 'rb')) # load sample result
    diff = np.sum(np.abs(occ0_step6 - occ0))
    print('occ0_step6',diff)
    diff = np.sum(np.abs(occ1_step6 - occ1))
    print('occ1_step6',diff)

    # ==================================================
    # ===== step 7/ forward-warp the flow to time t to get flow_t
    # ==================================================
    flow_t = interpflow(flow0, frame0, frame1, t)
    pickle.dump(flow_t, open('flow_t.step7.data', 'wb')) # save your intermediate result
    # ====== score
    flow_t       = pickle.load(open('flow_t.step7.data', 'rb')) # load your intermediate result
    flow_t_step7 = pickle.load(open('flow_t.step7.sample', 'rb')) # load sample result
    diff = np.sum(np.abs(flow_t-flow_t_step7))
    print('flow_t_step7',diff)

    # ==================================================
    # ===== step 8/ find holes in the estimated flow_t
    # ==================================================
    holes1 = find_holes(flow_t)
    pickle.dump(holes1, open('holes1.step8.data', 'wb')) # save your intermediate result
    # ====== score
    holes1       = pickle.load(open('holes1.step8.data','rb')) # load your intermediate result
    holes1_step8 = pickle.load(open('holes1.step8.sample','rb')) # load sample result
    diff = np.sum(np.abs(holes1-holes1_step8))
    print('holes1_step8',diff)

    # ===== fill in any hole in flow_t using an outside-in strategy
    flow_t = holefill(flow_t, holes1)
    pickle.dump(flow_t, open('flow_t.step8.data', 'wb')) # save your intermediate result
    # ====== score
    flow_t       = pickle.load(open('flow_t.step8.data', 'rb')) # load your intermediate result
    flow_t_step8 = pickle.load(open('flow_t.step8.sample', 'rb')) # load sample result
    diff = np.sum(np.abs(flow_t-flow_t_step8))
    print('flow_t_step8',diff)

    # ==================================================
    # ===== 9/ inverse-warp frame 0 and frame 1 to the target time t
    # ==================================================
    
    frame_t = warpimages(flow_t, frame0, frame1, occ0, occ1, t)
    pickle.dump(frame_t, open('frame_t.step9.data', 'wb')) # save your intermediate result
    # ====== score
    frame_t       = pickle.load(open('frame_t.step9.data', 'rb')) # load your intermediate result
    frame_t_step9 = pickle.load(open('frame_t.step9.sample', 'rb')) # load sample result
    diff = np.sqrt(np.mean(np.square(frame_t.astype(np.float32)-frame_t_step9.astype(np.float32))))
    print('frame_t',diff)

    
    frame_t       = pickle.load(open('frame_t.step9.data', 'rb')) # load your intermediate result
    frame_t_step9 = pickle.load(open('frame_t.step9.sample', 'rb')) # load sample result

    return frame_t


if __name__ == "__main__":

    print('==================================================')
    print('PSU CS 410/510, Winter 2020, HW3: video frame interpolation')
    print('==================================================')

    # ===================================
    # example:
    # python interp_skeleton.py frame0.png frame1.png flow0.flo frame05.png
    # ===================================
    path_file_image_0 = sys.argv[1]
    path_file_image_1 = sys.argv[2]
    path_file_flow    = sys.argv[3]
    path_file_image_result = sys.argv[4]

    # ===== read 2 input images and flow
    frame0 = cv2.imread(path_file_image_0)
    frame1 = cv2.imread(path_file_image_1)
    flow0  = readFlowFile(path_file_flow)

    # ===== interpolate an intermediate frame at t, t in [0,1]
    frame_t= internp(frame0=frame0, frame1=frame1, t=0.5, flow0=flow0)
    cv2.imwrite(filename=path_file_image_result, img=(frame_t * 1.0).clip(0.0, 255.0).astype(np.uint8))
