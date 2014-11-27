from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import six
import uuid
import numpy as np
import tempfile
from io import BytesIO
import base64

def export(sequence, filename, rate=30, bitrate=None,
           width=None, height=None, codec='mpeg4', format='yuv420p',
           autoscale=True):
    """Export a sequence of images as a standard video file.

    N.B. If the quality and detail are insufficient, increase the
    bitrate.

    Parameters
    ----------
    sequence : any iterator or array of array-like images
        The images should have two dimensions plus an
        optional third dimensions representing color.
    filename : string
        name of output file
    rate : integer
        frame rate of output file, 30 by default
    bitrate : integer
        Video bitrate is crudely guessed if None is given.
    width : integer
        By default, set the width of the images.
    height : integer
        By default, set the  height of the images. If width is specified
        and height is not, the height is autoscaled to maintain the aspect
        ratio.
    codec : string
        a valid video encoding, 'mpeg4' by default
    format: string
        Video stream format, 'yuv420p' by default.
    autoscale : boolean
        Linearly rescale the brightness to use the full gamut of black to
        white values. If the datatype of the images is not 'uint8', this must
        be set to True, as it is by default.
        
    """
    try:
        import av
    except ImportError:
        raise("This feature requires PyAV with FFmpeg or libav installed.")
    output = av.open(filename, 'w')
    stream = output.add_stream(bytes(codec), rate)
    stream.pix_fmt = bytes(format)

    ndim = None
    for frame_no, img in enumerate(sequence):
        if not frame_no:
            # Inspect first frame to set up stream.
            if bitrate is None:
                bitrate = _estimate_bitrate(img.shape, rate)
                stream.bit_rate = int(bitrate)
            if width is None:
                stream.height = img.shape[0]
                stream.width = img.shape[1]
            else:
                stream.width = width
                stream.height = (height or
                                width * img.shape[0] // img.shape[1])
            ndim = img.ndim

        if ndim == 3:
            if img.shape.count(3) != 1:
                raise ValueError("Images have the wrong shape.")
            # This is a color image. Ensure that the color axis is axis 2.
            color_axis = img.shape.index(3)
            img = np.rollaxis(img, color_axis, 3)
        elif ndim == 2:
            # Expand into color to satisfy PyAV's expectation that images
            # be in color. (Without this, an assert is tripped.)
            img = np.repeat(np.expand_dims(img, 2), 3, axis=2)
        else:
            raise ValueError("Images have the wrong shape.")

        # PyAV requires uint8.
        if img.dtype is not np.uint8 and (not autoscale):
            raise ValueError("Autoscaling must be turned on if the image "
                             "data type is not uint8. Convert the datatype "
                             "manually if you want to turn off autoscale.")
        if autoscale:
            normed = (img - img.min()) / (img.max() - img.min())
            img = (255 * normed).astype('uint8')

        frame = av.VideoFrame.from_ndarray(np.asarray(img), format=b'bgr24')
        packet = stream.encode(frame)
        output.mux(packet)

    output.close()


def play(sequence, rate=30, bitrate=None,
         width=None, height=None, autoscale=True):
    """In an IPython notebook, display a sequence of images as
    an embedded video.

    N.B. If the quality and detail are insufficient, increase the
    bit rate.

    Parameters
    ----------
    sequence : any iterator or array of array-like images
        The images should have two dimensions plus an
        optional third dimensions representing color.
    rate : integer
        frame rate of output file, 30 by default
    bitrate : integer
        Video bitrate is crudely guessed if None is given.
    width : integer
        By default, set the width of the images.
    height : integer
        By default, set the  height of the images. If width is specified
        and height is not, the height is autoscaled to maintain the aspect
        ratio.
    autoscale : boolean
        Linearly rescale the brightness to use the full gamut of black to
        white values. If the datatype of the images is not 'uint8', this must
        be set to True, as it is by default.
        
    """
    try:
        from IPython.display import display
    except ImportError:
        raise ImportError("This feature requires IPython.")
    with tempfile.NamedTemporaryFile(suffix='.webm') as temp:
        export(sequence, bytes(temp.name), codec='libvpx', rate=rate, 
               width=width, height=height, bitrate=bitrate, format='yuv420p',
               autoscale=True)
        temp.flush()
        display(repr_video(temp.name, 'x-webm'))


def repr_video(fname, mimetype):
    """Load the video in the file `fname`, with given mimetype,
    and display as HTML5 video.
    """
    try:
       from IPython.display import HTML
    except ImportError:
        raise ImportError("This feature requires IPython.")
    video_encoded = open(fname, "rb").read().encode("base64")

    video_tag = """<video controls>
<source alt="test" src="data:video/{0};base64,{1}" type="video/webm">
Use Google Chrome browser.</video>""".format(mimetype, video_encoded)
    return HTML(data=video_tag)


def _scrollable_stack(sequence, width, normalize=True):
    # See the public function, scrollable_stack, below.
    # This does all the work, and it returns a string of HTML and JS code,
    # as expected by Frame._repr_html_(). The public function wraps this
    # in IPython.display.HTML for the user.
    from IPython.display import Javascript, HTML, display_png
    from jinja2 import Template

    SCROLL_STACK_JS = Template("""
require(['jquery'], function() {
  if (!(window.PIMS)) {
    var stack_cursors = {};
    window.PIMS = {stack_cursors: {}};
  }
  $('#stack-{{stack_id}}-slice-0').css('display', 'block');
  window.PIMS.stack_cursors['{{stack_id}}'] = 0;
});

require(['jquery'],
$('#image-stack-{{stack_id}}').bind('mousewheel DOMMouseScroll', function(e) {
  var direction;
  var cursor = window.PIMS.stack_cursors['{{stack_id}}'];
  e.preventDefault();
  if (e.type == 'mousewheel') {
    direction = e.originalEvent.wheelDelta < 0;
  }
  else if (e.type == 'DOMMouseScroll') {
    direction = e.originalEvent.detail < 0;
  }
  var delta = direction * 2 - 1;
  if (cursor + delta < 0) {
    return;
  }
  else if (cursor + delta > {{length}} - 1) {
    return;
  }
  $('#stack-{{stack_id}}-slice-' + cursor).css('display', 'none');
  $('#stack-{{stack_id}}-slice-' + (cursor + delta)).css('display', 'block');
  window.PIMS.stack_cursors['{{stack_id}}'] = cursor + delta;
}));""")
    TAG = Template('<img src="data:image/png;base64,{{data}}" '
                   'style="display: none;" '
                   'id="stack-{{stack_id}}-slice-{{i}}" />')
    WRAPPER = Template('<div id="image-stack-{{stack_id}}", style='
                       '"width: {{width}}; float: left; display: inline;">')
    stack_id = uuid.uuid4()  # random unique identifier
    js = SCROLL_STACK_JS.render(length=len(sequence), stack_id=stack_id)
    output = '<script>{0}</script>'.format(js)
    output += WRAPPER.render(width=width, stack_id=stack_id)
    if normalize:
        sequence = _normalize(np.asarray(sequence))
    for i, s in enumerate(sequence):
        output += TAG.render(
            data=base64.b64encode(_as_png(s, width, normalize=False)),
            stack_id=stack_id, i=i)
    output += "</div>"
    return output


def scrollable_stack(sequence, width=512, normalize=True):
    """Display a sequence or 3D stack of frames as an interactive image
    that responds to scrolling.

    Parameters
    ----------
    sequence: a 3D Frame (or any array) or an iterable of 2D Frames (or arrays)
    width: integer
        Optional, defaults to 512. The height is auto-scaled.
    normalize : Rescale the brightness to fill the gamut. All pixels in the
        stack rescaled uniformly.

    Returns
    -------
    an interactive image, contained in a IPython.display.HTML object
    """
    from IPython.display import HTML
    return HTML(_scrollable_stack(sequence, width=width, normalize=normalize))


def _as_png(arr, width, normalize=True):
    "Create a PNG image buffer from an array."
    from PIL import Image
    w = width  # for brevity
    h = arr.shape[0] * w // arr.shape[1]
    if normalize:
        arr = _normalize(arr)
    img = Image.fromarray((arr * 255).astype('uint8')).resize((w, h))
    img_buffer = BytesIO()
    img.save(img_buffer, format='png')
    return img_buffer.getvalue()


def _normalize(arr):
    ptp = arr.max() - arr.min()
    # Handle edge case of a flat image.
    if ptp == 0:
        ptp = 1
    scaled_arr = (arr - arr.min()) / ptp
    return scaled_arr


def _estimate_bitrate(shape, frame_rate):
    "Return a bitrate that will guarantee lossless video."
    # Total Pixels x 8 bits x 3 channels x FPS
    return shape[0] * shape[1] * 8 * 3 * frame_rate

def wavelength_to_rgb(wavelength, gamma=0.8):
    """This converts a given wavelength of light to an approximate RGB color.

    Parameters
    ----------
    wavelength : int or float
        the wavelength must be given in nanometers in the range from 380 nm 
        through 750 nm
    gamma : float
    
    Returns
    -------
    tuple of int
        RGB value

    References
    ----------
    Based on code by Dan Bruton
    http://www.physics.sfasu.edu/astro/color/spectra.html
    """
    wavelength = float(wavelength)
    if wavelength >= 380 and wavelength <= 440:
        attenuation = 0.3 + 0.7 * (wavelength - 380) / (440 - 380)
        R = ((-(wavelength - 440) / (440 - 380)) * attenuation) ** gamma
        G = 0.0
        B = (1.0 * attenuation) ** gamma
    elif wavelength >= 440 and wavelength <= 490:
        R = 0.0
        G = ((wavelength - 440) / (490 - 440)) ** gamma
        B = 1.0
    elif wavelength >= 490 and wavelength <= 510:
        R = 0.0
        G = 1.0
        B = (-(wavelength - 510) / (510 - 490)) ** gamma
    elif wavelength >= 510 and wavelength <= 580:
        R = ((wavelength - 510) / (580 - 510)) ** gamma
        G = 1.0
        B = 0.0
    elif wavelength >= 580 and wavelength <= 645:
        R = 1.0
        G = (-(wavelength - 645) / (645 - 580)) ** gamma
        B = 0.0
    elif wavelength >= 645 and wavelength <= 750:
        attenuation = 0.3 + 0.7 * (750 - wavelength) / (750 - 645)
        R = (1.0 * attenuation) ** gamma
        G = 0.0
        B = 0.0
    else:
        R = 0.0
        G = 0.0
        B = 0.0
    R *= 255
    G *= 255
    B *= 255
    return (np.uint8(R), np.uint8(G), np.uint8(B))
    
def to_rgb(image, wavelengths = None, normalize = True):    
    """This converts a greyscale or multichannel image to an RGB image, with 
    given channel wavelength(s) in nm.

    Parameters
    ----------
    image : ndarray
        Multichannel image (channel dimension is first dimension). When first
        dimension is longer than 4, the file is interpreted as a greyscale.
    wavelengths : int or float or list of int or list of float, optional
        Wavelength(s) in the range from 380 nm through 750 nm
    normalize : bool, optional
        Multichannel images will be downsampled to 8-bit RGB, if normalize is
        True. Greyscale images will always give 8-bit RGB.
    
    Returns
    -------
    ndarray of int
        RGB image, with inner dimension of length 3
    """
    # identify number of channels and resulting shape
    is_multichannel = image.ndim > 2 and image.shape[0] < 5
    if is_multichannel:
        channels = image.shape[0]
        shape_rgb = image.shape[1:] + (3,)
    else:
        channels = 1
        shape_rgb = image.shape + (3,)
    # identify rgb values of channels, if not given as parameter
    if wavelengths == None:
        # pick from standard colors Green, Magenta, Blue, Red
        rgbs = [(0,255,0), (255,0,255), (0,0,255), (255,0,0)][:channels]
    else:
        try:
            rgbs = [wavelength_to_rgb(nm) for nm in wavelengths[:channels]]
        except TypeError or IndexError:
            rgbs = [wavelength_to_rgb(wavelengths)]
    if channels != len(rgbs):
        raise IndexError('Not enough wavelength values to build rgb image')

    def _monochannel_to_rgb(image, rgb):        
        image_rgb = _normalize(image) # float between 0 and 1
        image_rgb = np.repeat(np.expand_dims(image_rgb,-1),3,-1)
        image_rgb = np.multiply(image_rgb, rgb)
        return image_rgb.astype('uint8')

    if is_multichannel: 
        result = np.zeros(shape_rgb, dtype=np.uint16)
        for i in range(channels):
            result += _monochannel_to_rgb(image[i], rgbs[i])
    else:
        result = _monochannel_to_rgb(image, rgbs[i])
    
    if is_multichannel and normalize:    
        norm = result.max()
        result = (result / norm * 255).astype('uint8')
    
    return result
