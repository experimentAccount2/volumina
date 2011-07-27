from PyQt4.QtCore import QObject, QRect, pyqtSignal
from PyQt4.QtGui import QImage
from qimage2ndarray import gray2qimage, array2qimage, alpha_view, rgb_view
from asyncabcs import SourceABC, RequestABC
from volumeeditor.slicingtools import is_bounded, slicing2rect, rect2slicing, slicing2shape, is_pure_slicing
from datasources import ConstantSource
import numpy as np

class ImageSource( QObject ):
    '''Partial implemented base class for image sources'''
    isDirty = pyqtSignal( QRect )

    def request( self, rect ):
        raise NotImplementedError

    def setDirty( self, slicing ):
        if not is_pure_slicing(slicing):
            raise Exception('dirty region: slicing is not pure')
        if not is_bounded( slicing ):
            self.isDirty.emit(QRect()) # empty rect == everything is dirty
        else:
            self.isDirty.emit(slicing2rect( slicing ))
assert issubclass(ImageSource, SourceABC)



class GrayscaleImageRequest( object ):
    def __init__( self, arrayrequest ):
        self._arrayreq = arrayrequest

    def wait( self ):
        a = self._arrayreq.wait()
        a = a.squeeze()
        img = gray2qimage(a)
        return img.convertToFormat(QImage.Format_ARGB32_Premultiplied)        
    def notify( self, callback, **kwargs ):
        self._arrayreq.notify(self._onNotify, package = (callback, kwargs))

    def _onNotify( self, result, package ):
        img = self.wait()
        callback = package[0]
        kwargs = package[1]
        callback( img, **kwargs )
assert issubclass(GrayscaleImageRequest, RequestABC)

class GrayscaleImageSource( ImageSource ):
    def __init__( self, arraySource2D ):
        assert isinstance(arraySource2D, SourceABC)
        super(GrayscaleImageSource, self).__init__()
        self._arraySource2D = arraySource2D
        self._arraySource2D.isDirty.connect(self.setDirty)

    def request( self, qrect ):
        assert isinstance(qrect, QRect)
        s = rect2slicing(qrect)
        req = self._arraySource2D.request(s)
        return GrayscaleImageRequest( req )
assert issubclass(GrayscaleImageSource, SourceABC)



class RGBAImageRequest( object ):
    def __init__( self, r, g, b, a, shape ):
        self._requests = r, g, b, a
        shape.append(4)
        self._data = np.empty(shape, dtype=np.uint8)
        self._requestsFinished = 4 * [False,]

    def wait( self ):
        for i, req in enumerate(self._requests):
            a = self._requests[i].wait()
            a = a.squeeze()
            self._data[:,:,i] = a
        img = array2qimage(self._data)
        return img.convertToFormat(QImage.Format_ARGB32_Premultiplied)        
    def notify( self, callback, **kwargs ):
        for i in xrange(4):
            self._requests.notify(self._onNotify, package = (i, callback, kwargs))

    def _onNotify( self, result, package ):
        channel = package[0]
        self._requestsFinished[channel] = True
        if all(self._requestsFinished):
            img = self.wait()
            callback = package[1]
            kwargs = package[2]
            callback( img, **kwargs )
assert issubclass(RGBAImageRequest, RequestABC)

class RGBAImageSource( ImageSource ):
    def __init__( self, red, green, blue, alpha ):
        '''
        If you don't want to set all the channels,
        a ConstantSource may be used as a replacement for
        the missing channels.

        red, green, blue, alpha - 2d array sources

        '''
        channels = [red, green, blue, alpha]
        for channel in channels: 
                assert isinstance(channel, SourceABC) , 'channel has wrong type: %s' % str(type(channel))

        super(RGBAImageSource, self).__init__()
        self._channels = channels
        for arraySource in self._channels:
            arraySource.isDirty.connect(self.setDirty)

    def request( self, qrect ):
        assert isinstance(qrect, QRect)
        s = rect2slicing( qrect )
        r = self._channels[0].request(s)
        g = self._channels[1].request(s)
        b = self._channels[2].request(s)
        a = self._channels[3].request(s)
        shape = []
        for t in slicing2shape(s):
            if t > 1:
                shape.append(t)
        assert len(shape) == 2
        return RGBAImageRequest( r, g, b, a, shape )
assert issubclass(RGBAImageSource, SourceABC)






import unittest as ut
class GrayscaleImageSourceTest( ut.TestCase ):
    def setUp( self ):
        from scipy.misc import lena
        from datasources import ArraySource
        self.raw = lena()
        self.ars = ArraySource(self.raw)
        self.ims = GrayscaleImageSource( self.ars )
        

    def testRequest( self ):
        imr = self.ims.request(QRect(0,0,512,512))
        def check(result, codon):
            self.assertEqual(codon, "unique")
            self.assertTrue(type(result) == QImage)
        imr.notify(check, codon="unique")

    def testSetDirty( self ):
        def checkAllDirty( rect ):
            self.assertTrue( rect.isEmpty() )

        def checkDirtyRect( rect ):
            self.assertEqual( rect.x(), 12 )
            self.assertEqual( rect.y(), 34 )
            self.assertEqual( rect.width(), 22 )
            self.assertEqual( rect.height(), 3  )

        # should mark everything dirty
        self.ims.isDirty.connect( checkAllDirty )
        self.ims.setDirty((slice(34,None), slice(12,34)))
        self.ims.isDirty.disconnect( checkAllDirty )

        # dirty subrect
        self.ims.isDirty.connect( checkDirtyRect )
        self.ims.setDirty((slice(34,37), slice(12,34)))
        self.ims.isDirty.disconnect( checkDirtyRect )



class RGBAImageSourceTest( ut.TestCase ):
    def setUp( self ):
        import numpy as np
        import os.path
        from datasources import ArraySource        
        from volumeeditor import _testing
        basedir = os.path.dirname(_testing.__file__)
        self.data = np.load(os.path.join(basedir, 'rgba129x104.npy'))
        self.red = ArraySource(self.data[:,:,0])
        self.green = ArraySource(self.data[:,:,1])
        self.blue = ArraySource(self.data[:,:,2])
        self.alpha = ArraySource(self.data[:,:,3])

        self.ims_rgba = RGBAImageSource( self.red, self.green, self.blue, self.alpha )
        self.ims_rgb = RGBAImageSource( self.red, self.green, self.blue )
        self.ims_rg = RGBAImageSource( self.red, self.green )
        self.ims_ba = RGBAImageSource( blue = self.blue, alpha = self.alpha )
        self.ims_a = RGBAImageSource( alpha = self.alpha )
        self.ims_none = RGBAImageSource()
        
    def testRgba( self ):
        img = self.ims_rgba.request(QRect(0,0,129,104)).wait()
        #img.save('rgba.tif')

    def testRgb( self ):
        img = self.ims_rgb.request(QRect(0,0,129,104)).wait()
        #img.save('rgb.tif')

    def testRg( self ):
        img = self.ims_rg.request(QRect(0,0,129,104)).wait()
        #img.save('rg.tif')

    def testBa( self ):
        img = self.ims_ba.request(QRect(0,0,129,104)).wait()
        #img.save('ba.tif')

    def testA( self ):
        img = self.ims_a.request(QRect(0,0,129,104)).wait()
        #img.save('a.tif')

    def testNone( self ):
        img = self.ims_none.request(QRect(0,0,129,104)).wait()
        #img.save('none.tif')

if __name__ == '__main__':
    ut.main()