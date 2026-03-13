from PIL import Image as PILImage
from PIL import ImageFile
from PIL.Image import DecompressionBombError, DecompressionBombWarning
import warnings

# pick a ceiling that makes sense for your archive
PILImage.MAX_IMAGE_PIXELS = 400_000_000

# optional: let large-but-allowed images load
ImageFile.LOAD_TRUNCATED_IMAGES = True

warnings.simplefilter("error", DecompressionBombWarning)